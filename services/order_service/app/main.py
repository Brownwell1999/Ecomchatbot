"""order-service: customers, orders and returns.

Every order endpoint needs the X-User-Id header (set by chat-service/gateway from the JWT).
Orders owned by someone else return 404, never 403, so order ids can't be probed.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.config import get_settings
from shared.db.models import Order, OrderItem, ReturnRequest, User
from shared.db.session import make_engine, make_sessionmaker
from shared.logging import RequestIdMiddleware, setup_logging
from shared.metrics import instrument
from shared.proxy import ForwardedPrefixMiddleware
from shared.security import verify_password

settings = get_settings()
logger = setup_logging("order_service", settings.log_level)

# From data/knowledge_base/return_policy.md
RETURN_WINDOW_DAYS = 30
ELECTRONICS_WINDOW_DAYS = 15
CHANGE_OF_MIND_FEE = Decimal("5.99")
FREE_RETURN_REASONS = {"defective", "damaged", "wrong_item"}
ReturnReason = Literal["changed_mind", "defective", "damaged", "wrong_item", "other"]


# ---------- schemas ----------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str


class DemoUserOut(UserOut):
    order_count: int


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class ItemOut(BaseModel):
    product_id: int
    name: str
    category: str
    quantity: int
    unit_price: Decimal


class OrderOut(BaseModel):
    id: int
    status: str
    total: Decimal
    carrier: str | None
    tracking_number: str | None
    placed_at: datetime
    delivered_at: datetime | None
    items: list[ItemOut]


class Eligibility(BaseModel):
    order_id: int
    eligible: bool
    reason_code: str
    message: str
    window_days: int
    days_since_delivery: int | None


class ReturnIn(BaseModel):
    reason: ReturnReason = "changed_mind"
    comment: str | None = Field(default=None, max_length=500)


class ReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    status: str
    reason: str
    refund_amount: Decimal
    created_at: datetime


# ---------- app ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine()
    app.state.sessions = make_sessionmaker(engine)
    yield
    await engine.dispose()


app = FastAPI(title="ShopBot order-service", version="0.2.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(ForwardedPrefixMiddleware)
instrument(app, "order-service")


async def get_session(request: Request):
    async with request.app.state.sessions() as session:
        yield session


def current_user_id(x_user_id: Annotated[int | None, Header()] = None) -> int:
    if x_user_id is None:
        raise HTTPException(status_code=401, detail="Login required")
    return x_user_id


Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[int, Depends(current_user_id)]


async def load_order(session: AsyncSession, order_id: int, user_id: int) -> Order:
    stmt = (
        select(Order)
        .where(Order.id == order_id, Order.user_id == user_id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    order = await session.scalar(stmt)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def to_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id, status=order.status, total=order.total, carrier=order.carrier,
        tracking_number=order.tracking_number, placed_at=order.placed_at,
        delivered_at=order.delivered_at,
        items=[ItemOut(product_id=i.product_id, name=i.product.name, category=i.product.category,
                       quantity=i.quantity, unit_price=i.unit_price) for i in order.items],
    )


def check_eligibility(order: Order, has_return: bool, now: datetime) -> Eligibility:
    """Pure policy logic (unit-tested)."""
    window = (ELECTRONICS_WINDOW_DAYS
              if any(i.product.category == "electronics" for i in order.items)
              else RETURN_WINDOW_DAYS)
    days = (now - order.delivered_at).days if order.delivered_at else None

    def result(ok: bool, code: str, msg: str) -> Eligibility:
        return Eligibility(order_id=order.id, eligible=ok, reason_code=code, message=msg,
                           window_days=window, days_since_delivery=days)

    if has_return or order.status == "returned":
        return result(False, "ALREADY_RETURNED", "A return already exists for this order.")
    if order.status == "cancelled":
        return result(False, "CANCELLED", "Cancelled orders can't be returned.")
    if order.status != "delivered":
        return result(False, "NOT_DELIVERED",
                      "The order hasn't been delivered yet, so it can't be returned. "
                      "Orders can be cancelled while their status is 'placed'.")
    if days is not None and days > window:
        late = days - window
        return result(False, "WINDOW_EXPIRED", f"The {window}-day return window ended "
                                               f"{late} day{'s' if late != 1 else ''} ago.")
    # ponytail: "opened beauty products are non-returnable" isn't modelled (no opened flag)
    return result(True, "ELIGIBLE", f"Eligible: delivered {days} days ago, within the "
                                    f"{window}-day return window.")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/auth/verify", response_model=UserOut)
async def verify(creds: Credentials, session: Session):
    user = await session.scalar(select(User).where(User.email == creds.email.lower()))
    if not user or not verify_password(creds.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return user


@app.get("/users/demo", response_model=list[DemoUserOut])
async def demo_users(session: Session, limit: Annotated[int, Query(ge=1, le=20)] = 6):
    """Demo accounts for the login picker (disabled in prod)."""
    if not (settings.debug_enabled or settings.demo_mode):
        raise HTTPException(status_code=404)
    stmt = (select(User, func.count(Order.id)).join(Order).group_by(User.id)
            .order_by(User.id).limit(limit))
    return [DemoUserOut(id=u.id, email=u.email, full_name=u.full_name, order_count=n)
            for u, n in (await session.execute(stmt)).all()]


@app.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, session: Session):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.get("/orders", response_model=list[OrderOut])
async def my_orders(session: Session, user_id: UserId,
                    limit: Annotated[int, Query(ge=1, le=20)] = 5):
    stmt = (select(Order).where(Order.user_id == user_id).order_by(Order.placed_at.desc())
            .limit(limit).options(selectinload(Order.items).selectinload(OrderItem.product)))
    return [to_out(o) for o in await session.scalars(stmt)]


@app.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, session: Session, user_id: UserId):
    return to_out(await load_order(session, order_id, user_id))


@app.get("/orders/{order_id}/return-eligibility", response_model=Eligibility)
async def return_eligibility(order_id: int, session: Session, user_id: UserId):
    order = await load_order(session, order_id, user_id)
    has_return = await session.scalar(
        select(func.count()).select_from(ReturnRequest).where(ReturnRequest.order_id == order_id))
    return check_eligibility(order, bool(has_return), settings.now())


@app.post("/orders/{order_id}/returns", response_model=ReturnOut, status_code=201)
async def create_return(order_id: int, body: ReturnIn, session: Session, user_id: UserId):
    order = await load_order(session, order_id, user_id)
    has_return = await session.scalar(
        select(func.count()).select_from(ReturnRequest).where(ReturnRequest.order_id == order_id))
    eligibility = check_eligibility(order, bool(has_return), settings.now())
    if not eligibility.eligible:
        raise HTTPException(status_code=409, detail=eligibility.model_dump(mode="json"))

    fee = Decimal("0") if body.reason in FREE_RETURN_REASONS else CHANGE_OF_MIND_FEE
    ret = ReturnRequest(order_id=order_id, user_id=user_id, reason=body.reason,
                        status="requested", refund_amount=max(order.total - fee, Decimal("0")))
    session.add(ret)
    await session.commit()
    await session.refresh(ret)
    return ret
