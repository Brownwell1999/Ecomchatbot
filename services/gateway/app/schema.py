"""Public GraphQL API (the only API the UI talks to)."""

import time
from collections.abc import AsyncGenerator
from datetime import datetime

import strawberry
from graphql import GraphQLError
from prometheus_client import Counter
from strawberry.extensions import MaxAliasesLimiter, MaxTokensLimiter, QueryDepthLimiter
from strawberry.scalars import JSON
from strawberry.types import Info

from shared.config import get_settings
from shared.security import create_token, decode_token

from .clients import ServiceClients, UpstreamError

MAX_MESSAGE_CHARS = 2000
settings = get_settings()
GRAPHQL_ERRORS = Counter("graphql_errors_total", "GraphQL errors returned", ["code"])


# ---------- types ----------
@strawberry.type
class Product:
    id: int
    name: str
    brand: str
    category: str
    price: float
    rating: float
    stock: int


@strawberry.type
class OrderItem:
    name: str
    quantity: int
    unit_price: float


@strawberry.type
class Order:
    id: int
    status: str
    total: float
    carrier: str | None
    tracking_number: str | None
    placed_at: datetime
    delivered_at: datetime | None
    items: list[OrderItem]


@strawberry.type
class Source:
    source: str
    section: str
    chunk_id: str
    score: float


@strawberry.type
class Message:
    id: str
    role: str
    content: str
    created_at: datetime
    products: list[Product]
    order: Order | None
    sources: list[Source]
    suggestions: list[str]


@strawberry.type
class ToolCall:
    name: str
    args: JSON
    output: JSON | None
    ok: bool
    latency_ms: int
    error: str | None


@strawberry.type
class GuardrailResult:
    name: str
    stage: str
    passed: bool
    action: str
    score: float | None
    detail: str


@strawberry.type
class LLMCall:
    step: str
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


@strawberry.type
class RetrievedChunk:
    chunk_id: str
    collection: str
    source: str
    section: str
    score: float
    used: bool
    content: str


@strawberry.type
class DebugInfo:
    request_id: str
    prompt_version: str
    latency_ms: int
    intent: str
    confidence: float
    nlu_source: str
    entities: JSON
    route: str
    tool_calls: list[ToolCall]
    llm_calls: list[LLMCall]
    retrieved_chunks: list[RetrievedChunk]
    retrieval_context: list[str]
    guardrails: list[GuardrailResult]
    fallback_used: bool
    history_messages_used: int


@strawberry.type
class ChatResponse:
    conversation_id: str
    message: Message
    debug: DebugInfo | None


@strawberry.type
class Conversation:
    id: str
    messages: list[Message]


@strawberry.type
class User:
    id: int
    email: str
    full_name: str


@strawberry.type
class DemoUser(User):
    order_count: int


@strawberry.type
class AuthPayload:
    token: str
    user: User


@strawberry.type
class ChatStreamEvent:
    """type: token (partial text) | final (validated response) | error."""

    type: str
    token: str | None = None
    response: ChatResponse | None = None
    error_code: str | None = None
    error_message: str | None = None


@strawberry.input
class SendMessageInput:
    text: str
    conversation_id: str | None = None


@strawberry.input
class FeedbackInput:
    conversation_id: str
    message_id: str
    rating: int = strawberry.field(description="1 = helpful, -1 = not helpful")
    comment: str | None = None


# ---------- dict -> type conversion ----------
def _message(d: dict) -> Message:
    order = d.get("order")
    return Message(
        id=d["id"], role=d["role"], content=d["content"],
        created_at=datetime.fromisoformat(d["created_at"]),
        products=[Product(**p) for p in d.get("products", [])],
        order=Order(**{**order,
                       "placed_at": datetime.fromisoformat(order["placed_at"]),
                       "delivered_at": (datetime.fromisoformat(order["delivered_at"])
                                        if order["delivered_at"] else None),
                       "items": [OrderItem(**i) for i in order["items"]]}) if order else None,
        sources=[Source(**s) for s in d.get("sources", [])],
        suggestions=d.get("suggestions", []),
    )


def _debug(d: dict | None) -> DebugInfo | None:
    if not d:
        return None
    return DebugInfo(**{
        **d,
        "tool_calls": [ToolCall(**t) for t in d["tool_calls"]],
        "llm_calls": [LLMCall(**c) for c in d["llm_calls"]],
        "retrieved_chunks": [RetrievedChunk(**c) for c in d["retrieved_chunks"]],
        "guardrails": [GuardrailResult(**g) for g in d["guardrails"]],
    })


def _response(data: dict) -> ChatResponse:
    return ChatResponse(conversation_id=data["conversation_id"],
                        message=_message(data["message"]), debug=_debug(data.get("debug")))


def _error(code: str, message: str, **extensions) -> GraphQLError:
    GRAPHQL_ERRORS.labels(code).inc()
    return GraphQLError(message, extensions={"code": code, **extensions})


def _validate(text: str) -> str:
    text = text.strip()
    if not text:
        raise _error("BAD_USER_INPUT", "Message must not be empty.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise _error("BAD_USER_INPUT", f"Message exceeds {MAX_MESSAGE_CHARS} characters.")
    return text


async def _rate_limit(info: Info, user_id: int | None) -> None:
    """Fixed one-minute window per signed-in user (or client IP), shared across replicas."""
    limit = settings.rate_limit_per_minute
    if not limit:
        return
    window = int(time.time() // 60)
    key = f"ratelimit:{user_id or info.context['client_ip']}:{window}"
    async with info.context["redis"].pipeline(transaction=True) as pipe:
        count, _ = await pipe.incr(key).expire(key, 60).execute()
    if count > limit:
        raise _error("RATE_LIMITED", f"Too many messages. Limit is {limit} per minute.",
                     retryAfterSeconds=60 - int(time.time()) % 60)


def _ws_user_id(info: Info) -> int | None:
    """WebSocket clients send the JWT in connectionParams (browsers can't set WS headers)."""
    if info.context["user_id"] is not None:
        return info.context["user_id"]
    params = info.context.get("connection_params") or {}
    token = str(params.get("authorization", "")).removeprefix("Bearer ").strip()
    return decode_token(token, settings.jwt_secret) if token else None


def _clients(info: Info) -> ServiceClients:
    return info.context["clients"]


# ---------- operations ----------
@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> str:
        return "ok"

    @strawberry.field
    async def me(self, info: Info) -> User | None:
        user_id = info.context["user_id"]
        if user_id is None:
            return None
        data = await _clients(info).get_user(user_id)
        return User(**data) if data else None

    @strawberry.field(description="Demo accounts for the login picker (dev/test only).")
    async def demo_users(self, info: Info) -> list[DemoUser]:
        return [DemoUser(**u) for u in await _clients(info).demo_users()]

    @strawberry.field
    async def conversation(self, info: Info, id: str) -> Conversation | None:
        data = await _clients(info).get_conversation(id)
        if data is None:
            return None
        return Conversation(id=data["conversation_id"],
                            messages=[_message(m) for m in data["messages"]])


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def login(self, info: Info, email: str, password: str) -> AuthPayload:
        user = await _clients(info).verify_credentials(email, password)
        if user is None:
            raise _error("UNAUTHENTICATED", "Invalid email or password.")
        token = create_token(user["id"], settings.jwt_secret, settings.jwt_ttl_minutes)
        return AuthPayload(token=token, user=User(**user))

    @strawberry.mutation
    async def send_message(self, info: Info, input: SendMessageInput) -> ChatResponse:
        text = _validate(input.text)
        await _rate_limit(info, info.context["user_id"])
        try:
            data = await _clients(info).send_message(input.conversation_id, text,
                                                     info.context["user_id"])
        except UpstreamError as exc:
            raise _error(exc.code, str(exc)) from exc
        return _response(data)

    @strawberry.mutation
    async def submit_feedback(self, info: Info, input: FeedbackInput) -> bool:
        if input.rating not in (1, -1):
            raise _error("BAD_USER_INPUT", "rating must be 1 or -1.")
        return await _clients(info).send_feedback({
            "conversation_id": input.conversation_id, "message_id": input.message_id,
            "rating": input.rating, "comment": input.comment,
            "user_id": info.context["user_id"]})

    @strawberry.mutation
    async def clear_conversation(self, info: Info, id: str) -> bool:
        return await _clients(info).delete_conversation(id)


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def send_message_stream(self, info: Info,
                                  input: SendMessageInput) -> AsyncGenerator[ChatStreamEvent]:
        """Same as sendMessage, but streams tokens (graphql-ws). The final event carries the
        guardrail-validated reply, which replaces the streamed text."""
        text = _validate(input.text)
        user_id = _ws_user_id(info)
        await _rate_limit(info, user_id)
        async for event in _clients(info).stream_message(input.conversation_id, text, user_id):
            if event["type"] == "token":
                yield ChatStreamEvent(type="token", token=event["text"])
            elif event["type"] == "final":
                yield ChatStreamEvent(type="final", response=_response(event["response"]))
            else:
                GRAPHQL_ERRORS.labels(event["code"]).inc()
                yield ChatStreamEvent(type="error", error_code=event["code"],
                                      error_message=event["message"])


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    extensions=[
        # Protect the gateway from abusive queries (a common GraphQL security test area)
        QueryDepthLimiter(max_depth=8),
        MaxAliasesLimiter(max_alias_count=15),
        MaxTokensLimiter(max_token_count=2000),
    ],
)
