"""Store tools: LangChain @tool wrappers over catalog-service and order-service.

Tools are created per request so they are bound to the signed-in user (user_id is never an
argument the LLM could choose). The dialog graph invokes them deterministically; because they
are real LangChain tools, the same definitions could be bound to an agent via bind_tools().
"""

import time

import httpx
from langchain_core.tools import BaseTool, tool

from shared.logging import REQUEST_ID_HEADER, request_id_var

from .schemas import ToolCall


class StoreClient:
    def __init__(self, catalog: httpx.AsyncClient, orders: httpx.AsyncClient):
        self.catalog = catalog
        self.orders = orders

    @staticmethod
    def _headers(user_id: int | None = None) -> dict[str, str]:
        headers = {REQUEST_ID_HEADER: request_id_var.get()}
        if user_id is not None:
            headers["X-User-Id"] = str(user_id)
        return headers

    async def search_products(self, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        resp = await self.catalog.get("/products", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def get_products(self, ids: list[int]) -> list[dict]:
        resp = await self.catalog.post("/products/batch", json=ids, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _order_get(self, path: str, user_id: int) -> dict | list | None:
        resp = await self.orders.get(path, headers=self._headers(user_id))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def create_return(self, user_id: int, order_id: int, reason: str) -> dict:
        resp = await self.orders.post(f"/orders/{order_id}/returns", json={"reason": reason},
                                      headers=self._headers(user_id))
        if resp.status_code == 409:  # no longer eligible
            return {"error": "not_eligible", **resp.json()["detail"]}
        resp.raise_for_status()
        return resp.json()


def build_tools(store: StoreClient, user_id: int | None) -> dict[str, BaseTool]:
    @tool
    async def search_products(query: str | None = None, category: str | None = None,
                              brand: str | None = None, min_price: float | None = None,
                              max_price: float | None = None, in_stock: bool = False) -> dict:
        """Keyword search in the product catalog with optional filters."""
        return await store.search_products(q=query, category=category, brand=brand,
                                           min_price=min_price, max_price=max_price,
                                           in_stock=in_stock, limit=6)

    @tool
    async def get_products(ids: list[int]) -> list[dict]:
        """Fetch products by id (used after semantic search)."""
        return await store.get_products(ids)

    @tool
    async def get_order(order_id: int) -> dict | None:
        """Status, tracking and items of one of the signed-in customer's orders."""
        return await store._order_get(f"/orders/{order_id}", user_id)

    @tool
    async def list_orders(limit: int = 5) -> list[dict]:
        """The signed-in customer's most recent orders."""
        return await store._order_get(f"/orders?limit={limit}", user_id) or []

    @tool
    async def check_return_eligibility(order_id: int) -> dict | None:
        """Whether an order can be returned under the return policy, and why."""
        return await store._order_get(f"/orders/{order_id}/return-eligibility", user_id)

    @tool
    async def create_return(order_id: int, reason: str = "changed_mind") -> dict:
        """Create a return request. Only call after the customer confirmed."""
        return await store.create_return(user_id, order_id, reason)

    return {t.name: t for t in (search_products, get_products, get_order, list_orders,
                                check_return_eligibility, create_return)}


async def call_tool(tool_: BaseTool, args: dict, calls: list[ToolCall]):
    """Invoke a tool and record it for the debug trace."""
    start = time.perf_counter()
    try:
        result = await tool_.ainvoke(args)
    except Exception as exc:
        calls.append(ToolCall(name=tool_.name, args=args, ok=False, error=str(exc),
                              latency_ms=int((time.perf_counter() - start) * 1000)))
        raise
    calls.append(ToolCall(name=tool_.name, args=args, output=result, ok=True,
                          latency_ms=int((time.perf_counter() - start) * 1000)))
    return result
