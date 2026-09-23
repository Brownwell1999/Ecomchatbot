"""catalog-service: product search and details (read-only)."""

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.db.models import Product
from shared.db.session import make_engine, make_sessionmaker
from shared.logging import RequestIdMiddleware, setup_logging
from shared.metrics import instrument

settings = get_settings()
logger = setup_logging("catalog_service", settings.log_level)

Category = Literal["electronics", "fashion", "footwear", "home_kitchen", "beauty", "sports"]
# Words that carry no search meaning ("show me some shoes" -> "shoes")
STOPWORDS = {"a", "an", "the", "some", "any", "for", "with", "me", "show", "find", "i", "want",
             "need", "looking", "buy", "under", "over", "below", "above", "cheap", "best", "good",
             "and", "or", "of", "to", "in", "on", "my", "please", "recommend"}


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    brand: str
    category: str
    description: str
    price: Decimal
    stock: int
    rating: Decimal


class ProductPage(BaseModel):
    total: int
    items: list[ProductOut]


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine()
    app.state.sessions = make_sessionmaker(engine)
    yield
    await engine.dispose()


app = FastAPI(title="ShopBot catalog-service", version="0.2.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
instrument(app, "catalog-service")


async def get_session(request: Request):
    async with request.app.state.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


def keyword_terms(q: str) -> list[str]:
    """'Running shoes under $100' -> ['running', 'shoe'] (naive singularisation)."""
    words = [w.strip(".,!?$").lower() for w in q.split()]
    # ponytail: strip trailing "s" as a poor man's stemmer; use Postgres full-text search if
    # recall on plurals/synonyms becomes a problem
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w
            for w in words if w and w not in STOPWORDS and not w.isdigit()]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/products", response_model=ProductPage)
async def search_products(
    session: Session,
    q: Annotated[str | None, Query(max_length=200)] = None,
    category: Category | None = None,
    brand: Annotated[str | None, Query(max_length=100)] = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    in_stock: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    filters = []
    for term in keyword_terms(q or ""):
        pattern = f"%{term}%"
        filters.append(or_(Product.name.ilike(pattern), Product.category.ilike(pattern),
                           Product.brand.ilike(pattern), Product.description.ilike(pattern)))
    if category:
        filters.append(Product.category == category)
    if brand:
        filters.append(Product.brand.ilike(brand))
    if min_price is not None:
        filters.append(Product.price >= min_price)
    if max_price is not None:
        filters.append(Product.price <= max_price)
    if in_stock:
        filters.append(Product.stock > 0)

    stmt = select(Product).where(and_(*filters)).order_by(Product.rating.desc(), Product.id)
    rows = (await session.scalars(stmt)).all()
    return ProductPage(total=len(rows), items=rows[:limit])


@app.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, session: Session):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/products/batch", response_model=list[ProductOut])
async def get_products(ids: list[int], session: Session):
    """Fetch several products in the given order (used after semantic search)."""
    rows = {p.id: p for p in await session.scalars(select(Product).where(Product.id.in_(ids)))}
    return [rows[i] for i in ids if i in rows]
