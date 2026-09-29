"""Public GraphQL API (the only API the UI talks to)."""

import re
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

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
class AgentStep:
    step: int
    thought: str
    tool: str | None
    args: JSON
    ok: bool


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
    agent_steps: list[AgentStep] = strawberry.field(default_factory=list)
    stopped_reason: str | None = None


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
class LabUser:
    """An AI Testing Lab account (separate from ShopBot's demo customers)."""

    id: int
    email: str
    full_name: str
    role: str = strawberry.field(description="learner | admin")
    active: bool
    created_at: datetime
    last_login_at: datetime | None


@strawberry.type
class LabUserAdmin(LabUser):
    lessons_completed: int


@strawberry.type
class LabAuthPayload:
    token: str
    user: LabUser


@strawberry.type
class LessonProgress:
    lesson_id: str
    completed_at: datetime


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
    agent_mode: bool = strawberry.field(
        default=False, description="AI Testing Lab: let the LLM choose tools itself (opt-in).")


@strawberry.input
class FeedbackInput:
    conversation_id: str
    message_id: str
    rating: int = strawberry.field(description="1 = helpful, -1 = not helpful")
    comment: str | None = None


@strawberry.input
class LabSignupInput:
    email: str
    full_name: str
    password: str


# ---------- dict -> type conversion ----------
def _dt(value: str | None) -> datetime | None:
    """DB timestamps are naive UTC; mark them as UTC so browsers don't read them as local time."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _lab_user(d: dict, cls: type = LabUser):
    return cls(**{**d, "created_at": _dt(d["created_at"]),
                  "last_login_at": _dt(d["last_login_at"])})


def _progress(items: list[dict]) -> list[LessonProgress]:
    return [LessonProgress(lesson_id=p["lesson_id"], completed_at=_dt(p["completed_at"]))
            for p in items]


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
        "agent_steps": [AgentStep(**s) for s in d.get("agent_steps", [])],
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


async def _rate_limit(info: Info, user_id: int | str | None) -> None:
    """Fixed per-minute and per-day windows per signed-in customer or lab user (or client IP),
    in Redis so every replica shares them."""
    who, now = user_id or info.context["client_ip"], int(time.time())
    for limit, seconds, label in ((settings.rate_limit_per_minute, 60, "minute"),
                                  (settings.rate_limit_per_day, 86400, "day")):
        if not limit:
            continue
        key = f"ratelimit:{label}:{who}:{now // seconds}"
        async with info.context["redis"].pipeline(transaction=True) as pipe:
            count, _ = await pipe.incr(key).expire(key, seconds).execute()
        if count > limit:
            raise _error("RATE_LIMITED", f"Too many messages. Limit is {limit} per {label}.",
                         retryAfterSeconds=seconds - now % seconds)


def _ws_user_id(info: Info) -> int | None:
    """WebSocket clients send the JWT in connectionParams (browsers can't set WS headers)."""
    if info.context["user_id"] is not None:
        return info.context["user_id"]
    params = info.context.get("connection_params") or {}
    token = str(params.get("authorization", "")).removeprefix("Bearer ").strip()
    return decode_token(token, settings.jwt_secret) if token else None


def _clients(info: Info) -> ServiceClients:
    return info.context["clients"]


# ---------- AI Testing Lab access ----------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _lab_user_id(info: Info) -> int | None:
    """Lab token from the X-Lab-Token header, or connectionParams.labToken on WebSockets."""
    if info.context["lab_user_id"] is not None:
        return info.context["lab_user_id"]
    token = str((info.context.get("connection_params") or {}).get("labToken", "")).strip()
    return decode_token(token, settings.jwt_secret, scope="lab") if token else None


async def _current_lab_user(info: Info) -> dict | None:
    """The signed-in, still-active lab user. Looked up on every call, so disabling an account
    takes effect immediately even though its token hasn't expired."""
    user_id = _lab_user_id(info)
    if user_id is None:
        return None
    user = await _clients(info).lab_user(user_id)
    return user if user and user["active"] else None


async def _require_lab_user(info: Info) -> dict:
    user = await _current_lab_user(info)
    if user is None:
        raise _error("UNAUTHENTICATED", "Sign in to the AI Testing Lab to continue.")
    return user


async def _require_admin(info: Info) -> dict:
    user = await _require_lab_user(info)
    if user["role"] != "admin":
        raise _error("FORBIDDEN", "Admins only.")
    return user


async def _chat_access(info: Info) -> dict | None:
    """Who may chat: anyone in dev/test, only lab users when LAB_AUTH_REQUIRED (prod).
    A lab user also gets the debug trace - it is what the lessons inspect."""
    if settings.lab_auth_required:
        return await _require_lab_user(info)
    return await _current_lab_user(info)


async def _auth_rate_limit(info: Info) -> None:
    """Sign-up/login attempts per client IP (brute-force protection)."""
    limit = settings.lab_auth_rate_limit_per_minute
    if not limit:
        return
    now = int(time.time())
    key = f"ratelimit:labauth:{info.context['client_ip']}:{now // 60}"
    async with info.context["redis"].pipeline(transaction=True) as pipe:
        count, _ = await pipe.incr(key).expire(key, 60).execute()
    if count > limit:
        raise _error("RATE_LIMITED", "Too many attempts. Please wait a minute and try again.",
                     retryAfterSeconds=60 - now % 60)


def _validate_signup(data: LabSignupInput) -> tuple[str, str, str]:
    email, name, password = data.email.strip().lower(), data.full_name.strip(), data.password
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise _error("BAD_USER_INPUT", "Enter a valid email address.", field="email")
    if not 1 <= len(name) <= 100:
        raise _error("BAD_USER_INPUT", "Enter your name (up to 100 characters).", field="fullName")
    if (len(password) < 8 or len(password) > 200 or not re.search(r"[A-Za-z]", password)
            or not re.search(r"\d", password)):
        raise _error("BAD_USER_INPUT", "Password needs at least 8 characters, "
                     "including a letter and a number.", field="password")
    return email, name, password


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
        await _chat_access(info)
        data = await _clients(info).get_conversation(id)
        if data is None:
            return None
        return Conversation(id=data["conversation_id"],
                            messages=[_message(m) for m in data["messages"]])

    # ---------- AI Testing Lab ----------
    @strawberry.field(description="The signed-in lab user, or null.")
    async def lab_me(self, info: Info) -> LabUser | None:
        user = await _current_lab_user(info)
        return _lab_user(user) if user else None

    @strawberry.field(description="Lessons the signed-in lab user has completed.")
    async def lab_progress(self, info: Info) -> list[LessonProgress]:
        user = await _require_lab_user(info)
        return _progress(await _clients(info).lab_progress(user["id"]))

    @strawberry.field(description="All lab accounts with progress (admins only).")
    async def lab_users(self, info: Info) -> list[LabUserAdmin]:
        await _require_admin(info)
        return [_lab_user(u, LabUserAdmin) for u in await _clients(info).lab_users()]


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
        lab_user = await _chat_access(info)
        user_id = info.context["user_id"]
        await _rate_limit(info, user_id or (f"lab{lab_user['id']}" if lab_user else None))
        try:
            data = await _clients(info).send_message(input.conversation_id, text, user_id,
                                                     include_debug=lab_user is not None,
                                                     agent_mode=input.agent_mode)
        except UpstreamError as exc:
            raise _error(exc.code, str(exc)) from exc
        return _response(data)

    @strawberry.mutation
    async def submit_feedback(self, info: Info, input: FeedbackInput) -> bool:
        if input.rating not in (1, -1):
            raise _error("BAD_USER_INPUT", "rating must be 1 or -1.")
        await _chat_access(info)
        return await _clients(info).send_feedback({
            "conversation_id": input.conversation_id, "message_id": input.message_id,
            "rating": input.rating, "comment": input.comment,
            "user_id": info.context["user_id"]})

    @strawberry.mutation
    async def clear_conversation(self, info: Info, id: str) -> bool:
        await _chat_access(info)
        return await _clients(info).delete_conversation(id)

    # ---------- AI Testing Lab ----------
    @strawberry.mutation(description="Create a learner account and sign in.")
    async def lab_signup(self, info: Info, input: LabSignupInput) -> LabAuthPayload:
        await _auth_rate_limit(info)
        email, name, password = _validate_signup(input)
        try:
            user = await _clients(info).lab_register(email, name, password)
        except UpstreamError as exc:
            raise _error(exc.code, str(exc)) from exc
        token = create_token(user["id"], settings.jwt_secret, settings.lab_token_ttl_minutes, "lab")
        return LabAuthPayload(token=token, user=_lab_user(user))

    @strawberry.mutation
    async def lab_login(self, info: Info, email: str, password: str) -> LabAuthPayload:
        await _auth_rate_limit(info)
        try:
            user = await _clients(info).lab_verify(email.strip().lower(), password)
        except UpstreamError as exc:
            raise _error(exc.code, str(exc)) from exc
        token = create_token(user["id"], settings.jwt_secret, settings.lab_token_ttl_minutes, "lab")
        return LabAuthPayload(token=token, user=_lab_user(user))

    @strawberry.mutation(description="Mark a lesson done; returns all completed lessons.")
    async def complete_lesson(self, info: Info, lesson_id: str) -> list[LessonProgress]:
        user = await _require_lab_user(info)
        try:
            return _progress(await _clients(info).lab_complete_lesson(user["id"], lesson_id))
        except UpstreamError as exc:
            raise _error(exc.code, str(exc)) from exc

    @strawberry.mutation(description="Change a lab user's role or enable/disable them "
                                     "(admins only).")
    async def lab_update_user(self, info: Info, id: int, role: str | None = None,
                              active: bool | None = None) -> LabUser:
        admin = await _require_admin(info)
        if role is not None and role not in ("learner", "admin"):
            raise _error("BAD_USER_INPUT", "role must be learner or admin.")
        if id == admin["id"] and (active is False or role == "learner"):
            raise _error("BAD_USER_INPUT", "You can't disable or demote your own account.")
        changes = {k: v for k, v in {"role": role, "active": active}.items() if v is not None}
        user = await _clients(info).lab_update_user(id, changes)
        if user is None:
            raise _error("NOT_FOUND", "User not found.")
        return _lab_user(user)


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def send_message_stream(self, info: Info,
                                  input: SendMessageInput) -> AsyncGenerator[ChatStreamEvent]:
        """Same as sendMessage, but streams tokens (graphql-ws). The final event carries the
        guardrail-validated reply, which replaces the streamed text."""
        text = _validate(input.text)
        lab_user = await _chat_access(info)
        user_id = _ws_user_id(info)
        await _rate_limit(info, user_id or (f"lab{lab_user['id']}" if lab_user else None))
        async for event in _clients(info).stream_message(input.conversation_id, text, user_id,
                                                         include_debug=lab_user is not None,
                                                         agent_mode=input.agent_mode):
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
