"""Cart, checkout, place order and cancel (used by ShopBot's Agent mode).

Every endpoint needs the X-User-Id header (set by chat-service from the customer's JWT), so a
customer only ever sees and changes their own cart and orders. Existing endpoints are unchanged.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from shared.config import get_settings
from shared.db.models import Base, CartItem, Order, OrderItem, Product

router = APIRouter()
CANCELLABLE = {"placed"}  # once shipped, an order can only be returned, not cancelled


# ---------- pure logic (unit-tested) ----------
def cart_total(lines: list[tuple[Decimal, int]]) -> Decimal:
    """Sum of unit_price * quantity."""
    return sum((price * qty for price, qty in lines), Decimal("0"))


def can_cancel(status: str) -> bool:
    return status in CANCELLABLE


# ---------- schemas ----------
class CartLineOut(BaseModel):
    product_id: int
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    in_stock: bool


class CartOut(BaseModel):
    items: list[CartLineOut]
    total: Decimal


class AddItemIn(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=20)


# ---------- setup (called from order-service lifespan) ----------
async def ensure_cart_schema(engine: AsyncEngine) -> None:
    """Create cart_items if missing, and move order id counters past the seeded rows."""
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(
            c, tables=[CartItem.__table__], checkfirst=True))
        for table in ("orders", "order_items"):
            await conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM {table}))"))


# ---------- dependencies ----------
async def get_session(request: Request):
    async with request.app.state.sessions() as session:
        yield session


def current_user_id(x_user_id: Annotated[int | None, Header()] = None) -> int:
    if x_user_id is None:
        raise HTTPException(status_code=401, detail="Login required")
    return x_user_id


Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[int, Depends(current_user_id)]


async def load_cart(session: AsyncSession, user_id: int) -> list[CartItem]:
    stmt = (select(CartItem).where(CartItem.user_id == user_id)
            .options(selectinload(CartItem.product)).order_by(CartItem.id))
    return list(await session.scalars(stmt))


def cart_out(items: list[CartItem]) -> CartOut:
    lines = [CartLineOut(product_id=i.product_id, name=i.product.name, quantity=i.quantity,
                         unit_price=i.product.price, line_total=i.product.price * i.quantity,
                         in_stock=i.product.stock >= i.quantity) for i in items]
    return CartOut(items=lines, total=cart_total([(i.product.price, i.quantity) for i in items]))


# ---------- cart ----------
@router.get("/cart", response_model=CartOut)
async def view_cart(session: Session, user_id: UserId):
    return cart_out(await load_cart(session, user_id))


@router.post("/cart/items", response_model=CartOut, status_code=201)
async def add_to_cart(body: AddItemIn, session: Session, user_id: UserId):
    product = await session.get(Product, body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    item = await session.scalar(select(CartItem).where(
        CartItem.user_id == user_id, CartItem.product_id == body.product_id))
    quantity = body.quantity + (item.quantity if item else 0)
    if quantity > product.stock:
        raise HTTPException(status_code=409, detail=f"Only {product.stock} in stock")
    if item:
        item.quantity = quantity
    else:
        session.add(CartItem(user_id=user_id, product_id=body.product_id, quantity=quantity))
    await session.commit()
    return cart_out(await load_cart(session, user_id))


@router.delete("/cart/items/{product_id}", response_model=CartOut)
async def remove_from_cart(product_id: int, session: Session, user_id: UserId):
    await session.execute(delete(CartItem).where(
        CartItem.user_id == user_id, CartItem.product_id == product_id))
    await session.commit()
    return cart_out(await load_cart(session, user_id))


# ---------- checkout (review only) + place order ----------
@router.get("/checkout", response_model=CartOut)
async def checkout(session: Session, user_id: UserId):
    """Order summary for the customer to confirm. Changes nothing."""
    summary = cart_out(await load_cart(session, user_id))
    if not summary.items:
        raise HTTPException(status_code=409, detail="Your cart is empty")
    if not all(line.in_stock for line in summary.items):
        raise HTTPException(status_code=409, detail="Some items are no longer in stock")
    return summary


@router.post("/orders", status_code=201)
async def place_order(session: Session, user_id: UserId):
    """Turn the cart into an order (status 'placed'), take the stock, empty the cart."""
    from .main import load_order, to_out  # main.py includes this router

    items = await load_cart(session, user_id)
    if not items:
        raise HTTPException(status_code=409, detail="Your cart is empty")
    if any(i.product.stock < i.quantity for i in items):
        raise HTTPException(status_code=409, detail="Some items are no longer in stock")

    order = Order(user_id=user_id, status="placed", placed_at=get_settings().now(), carrier=None,
                  total=cart_total([(i.product.price, i.quantity) for i in items]))
    session.add(order)
    await session.flush()  # gets order.id
    for i in items:
        session.add(OrderItem(order_id=order.id, product_id=i.product_id, quantity=i.quantity,
                              unit_price=i.product.price))
        i.product.stock -= i.quantity
        await session.delete(i)
    await session.commit()
    return to_out(await load_order(session, order.id, user_id))


# ---------- cancel ----------
@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: int, session: Session, user_id: UserId):
    from .main import load_order, to_out  # main.py includes this router

    order = await load_order(session, order_id, user_id)  # other people's orders -> 404
    if not can_cancel(order.status):
        raise HTTPException(status_code=409,
                            detail=f"Order is {order.status}; only placed orders can be cancelled")
    order.status = "cancelled"
    for item in order.items:
        item.product.stock += item.quantity
    await session.commit()
    return to_out(await load_order(session, order_id, user_id))

