from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

MAX_MESSAGE_CHARS = 2000
CONVERSATION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class ChatRequest(BaseModel):
    conversation_id: str | None = Field(default=None, pattern=CONVERSATION_ID_PATTERN)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    user_id: int | None = None  # set by the gateway from the JWT, never by the browser
    # Set by the gateway for signed-in AI Testing Lab users: the debug trace is the lesson material
    include_debug: bool = False
    # AI Testing Lab "Agent mode" (opt-in): the LLM picks ShopBot's tools itself.
    # Default False = the existing fixed workflow, unchanged.
    agent_mode: bool = False

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


# ---------- structured payloads rendered as cards in the UI ----------
class ProductCard(BaseModel):
    id: int
    name: str
    brand: str
    category: str
    price: float
    rating: float
    stock: int


class OrderItemCard(BaseModel):
    name: str
    quantity: int
    unit_price: float


class OrderCard(BaseModel):
    id: int
    status: str
    total: float
    carrier: str | None
    tracking_number: str | None
    placed_at: datetime
    delivered_at: datetime | None
    items: list[OrderItemCard]


class Source(BaseModel):
    """Citation for a RAG answer."""

    source: str
    section: str
    chunk_id: str
    score: float


class MessageOut(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    products: list[ProductCard] = []
    order: OrderCard | None = None
    sources: list[Source] = []
    suggestions: list[str] = []


# ---------- debug / observability (dev & test only) ----------
class LLMCall(BaseModel):
    step: str  # nlu | respond | rag_answer | chat
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class ToolCall(BaseModel):
    """Maps to deepeval.test_case.ToolCall(name, input_parameters=args, output=output)."""

    name: str
    args: dict[str, Any]
    output: Any = None
    ok: bool
    latency_ms: int
    error: str | None = None


class AgentStep(BaseModel):
    """One step of the agent loop: what the LLM said, and the tool it chose (if any)."""

    step: int
    thought: str = ""  # the LLM's text alongside/instead of a tool call (its reasoning / plan)
    tool: str | None = None
    args: dict[str, Any] = {}
    ok: bool = True


class GuardrailResult(BaseModel):
    name: str  # pii | prompt_injection | prompt_guard | prompt_leak | sensitive_request | grounding
    stage: Literal["input", "output"]
    passed: bool
    action: Literal["allow", "mask", "block"]
    score: float | None = None
    detail: str = ""


class RetrievedChunk(BaseModel):
    chunk_id: str
    collection: str
    source: str
    section: str
    score: float
    used: bool  # passed the relevance threshold and went into the prompt
    content: str


class DebugInfo(BaseModel):
    request_id: str
    prompt_version: str
    latency_ms: int
    intent: str
    confidence: float
    nlu_source: str  # llm | rules | dialog
    entities: dict[str, Any]
    route: str
    tool_calls: list[ToolCall]
    llm_calls: list[LLMCall]
    retrieved_chunks: list[RetrievedChunk]
    retrieval_context: list[str]
    guardrails: list[GuardrailResult]
    fallback_used: bool
    history_messages_used: int
    agent_steps: list[AgentStep] = []  # agent mode only
    stopped_reason: str | None = None  # agent mode only: final_answer | max_steps


class ChatResponse(BaseModel):
    conversation_id: str
    message: MessageOut
    debug: DebugInfo | None = None


class ConversationOut(BaseModel):
    conversation_id: str
    messages: list[MessageOut]


class DialogState(BaseModel):
    """What the bot is waiting for between turns (slot filling / confirmation)."""

    awaiting: Literal["order_id", "return_confirmation"] | None = None
    intent: str | None = None
    order_id: int | None = None
    return_reason: str | None = None


class FeedbackIn(BaseModel):
    conversation_id: str = Field(pattern=CONVERSATION_ID_PATTERN)
    message_id: str = Field(min_length=1, max_length=64)
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=1000)
    user_id: int | None = None
