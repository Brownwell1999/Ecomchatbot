"""API gateway / BFF: single GraphQL entry point in front of the microservices."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.requests import HTTPConnection
from strawberry.fastapi import GraphQLRouter

from shared.config import get_settings
from shared.logging import RequestIdMiddleware, log_event, setup_logging
from shared.metrics import instrument
from shared.security import decode_token

from .clients import ServiceClients
from .schema import schema

settings = get_settings()
logger = setup_logging("gateway", settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # LLM calls can be slow on local CPU models, so the read timeout is generous
    timeout = httpx.Timeout(settings.llm_timeout_seconds + 30, connect=5)
    app.state.http = httpx.AsyncClient(base_url=settings.chat_service_url, timeout=timeout)
    orders = httpx.AsyncClient(base_url=settings.order_service_url, timeout=10)
    app.state.clients = ServiceClients(app.state.http, orders)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    log_event(logger, "gateway_started", chat_service_url=settings.chat_service_url,
              order_service_url=settings.order_service_url)
    yield
    await app.state.http.aclose()
    await orders.aclose()
    await app.state.redis.aclose()


async def get_context(connection: HTTPConnection) -> dict:
    """Works for HTTP and WebSocket. Invalid/expired tokens are treated as anonymous."""
    auth = connection.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    user_id = decode_token(token, settings.jwt_secret) if token else None
    # nginx sets X-Forwarded-For; direct callers fall back to the socket address
    client_ip = (connection.headers.get("x-forwarded-for", "").split(",")[0].strip()
                 or (connection.client.host if connection.client else "unknown"))
    return {"clients": connection.app.state.clients, "redis": connection.app.state.redis,
            "user_id": user_id, "client_ip": client_ip}


graphql_router = GraphQLRouter(
    schema,
    context_getter=get_context,
    graphql_ide="graphiql" if settings.debug_enabled else None,
)

app = FastAPI(title="ShopBot gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
instrument(app, "gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.include_router(graphql_router, prefix="/graphql")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request):
    try:
        resp = await request.app.state.http.get("/ready", timeout=3)
        downstream = "up" if resp.status_code == 200 else "down"
    except httpx.HTTPError:
        downstream = "down"
    status = 200 if downstream == "up" else 503
    return JSONResponse({"status": "ready" if status == 200 else "degraded",
                         "chat_service": downstream}, status_code=status)
