"""chat-service: the conversational "brain" (guardrails, NLU, dialog graph, RAG, LLM, memory)."""

import json
import re
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Path, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import text

from shared.config import get_settings
from shared.db.models import Feedback
from shared.db.session import make_engine, make_sessionmaker
from shared.logging import RequestIdMiddleware, log_event, request_id_var, setup_logging
from shared.metrics import instrument

from . import metrics
from .graph import ChatGraph, Trace
from .guardrails import Guardrails
from .llm import LLM, LLMUnavailableError
from .memory import RedisConversationStore
from .nlu import classify
from .prompts import CHAT_PROMPT, PERSONA, PROMPT_VERSION
from .rag import KB_COLLECTION, PRODUCT_COLLECTION, Retriever, make_embeddings, make_store
from .schemas import (
    CONVERSATION_ID_PATTERN,
    ChatRequest,
    ChatResponse,
    ConversationOut,
    FeedbackIn,
    GuardrailResult,
    LLMCall,
    RetrievedChunk,
)
from .service import ChatService
from .tools import StoreClient

settings = get_settings()
logger = setup_logging("chat_service", settings.log_level)

ConversationId = Path(pattern=CONVERSATION_ID_PATTERN)


def langfuse_callbacks():
    """Per-request Langfuse handler (LLM tracing) when keys are configured, else no-op."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return (lambda request_id: []), None
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    client = Langfuse(public_key=settings.langfuse_public_key,
                      secret_key=settings.langfuse_secret_key, host=settings.langfuse_host,
                      environment=settings.app_env)

    def callbacks(request_id: str) -> list:
        # Our request id doubles as the Langfuse trace id -> debug.requestId finds the trace
        ctx = {"trace_id": request_id} if re.fullmatch(r"[0-9a-f]{32}", request_id) else None
        return [CallbackHandler(public_key=settings.langfuse_public_key, trace_context=ctx)]

    return callbacks, client


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    catalog = httpx.AsyncClient(base_url=settings.catalog_service_url, timeout=10)
    orders = httpx.AsyncClient(base_url=settings.order_service_url, timeout=10)
    engine = make_engine()
    async with engine.begin() as conn:  # feedback table may be newer than the seeded schema
        await conn.run_sync(lambda c: Feedback.__table__.create(c, checkfirst=True))

    llm = LLM(settings)
    embeddings = make_embeddings(settings)
    kb = Retriever(make_store(settings, embeddings, KB_COLLECTION), KB_COLLECTION,
                   settings.rag_min_score, settings.rag_score_margin)
    products = Retriever(make_store(settings, embeddings, PRODUCT_COLLECTION),
                         PRODUCT_COLLECTION, settings.rag_min_score)
    graph = ChatGraph(llm, StoreClient(catalog, orders), kb, products, settings)
    guardrails = Guardrails(settings, [PERSONA, CHAT_PROMPT.messages[0].prompt.template])
    callbacks, langfuse = langfuse_callbacks()

    app.state.store = RedisConversationStore(redis, settings.chat_session_ttl_seconds)
    app.state.sessions = make_sessionmaker(engine)
    app.state.engine = engine
    app.state.llm, app.state.graph, app.state.guardrails = llm, graph, guardrails
    app.state.retrievers = {KB_COLLECTION: kb, PRODUCT_COLLECTION: products}
    app.state.chat = ChatService(
        graph, app.state.store, guardrails,
        history_turns=settings.chat_history_turns,
        primary_provider=settings.llm_provider,
        debug_enabled=settings.debug_enabled,
        callbacks=callbacks,
    )
    log_event(logger, "chat_service_started", models=llm.names,
              embedding_model=settings.embedding_model, prompt_version=PROMPT_VERSION,
              guardrail_classifier=bool(guardrails.classifier), langfuse=bool(langfuse),
              app_env=settings.app_env)
    yield
    if langfuse:
        langfuse.flush()
    await catalog.aclose()
    await orders.aclose()
    await redis.aclose()
    await engine.dispose()


app = FastAPI(title="ShopBot chat-service", version="0.3.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
instrument(app, "chat-service")


@app.exception_handler(LLMUnavailableError)
async def llm_unavailable_handler(request: Request, exc: LLMUnavailableError):
    return JSONResponse(
        status_code=503,
        content={"code": "LLM_UNAVAILABLE", "detail": "The assistant is temporarily unavailable."},
    )


@app.exception_handler(httpx.HTTPError)
async def upstream_handler(request: Request, exc: httpx.HTTPError):
    logger.error("Store service call failed: %s", exc)
    return JSONResponse(
        status_code=502,
        content={"code": "UPSTREAM_ERROR", "detail": "A store service is unavailable."},
    )


# ---------- health ----------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request):
    checks = {"redis": await request.app.state.store.ping()}
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("select 1"))
        checks["postgres"] = True
    except Exception:
        checks["postgres"] = False
    status = 200 if all(checks.values()) else 503
    return JSONResponse({k: "up" if v else "down" for k, v in checks.items()},
                        status_code=status)


# ---------- chat ----------
@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    return await request.app.state.chat.chat(body)


@app.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    """Server-sent events: `token` events while the reply is generated, then `final`."""
    request_id = request_id_var.get()  # middleware resets it before the body streams
    service: ChatService = request.app.state.chat

    async def events():
        token = request_id_var.set(request_id)
        try:
            async for event in service.chat_stream(body):
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            request_id_var.reset(token)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(request: Request, conversation_id: str = ConversationId):
    store = request.app.state.store
    if not await store.exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationOut(
        conversation_id=conversation_id, messages=await store.history(conversation_id)
    )


@app.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(request: Request, conversation_id: str = ConversationId):
    if not await request.app.state.store.delete(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)


@app.post("/feedback", status_code=201)
async def feedback(body: FeedbackIn, request: Request):
    history = await request.app.state.store.history(body.conversation_id)
    index = next((i for i, m in enumerate(history)
                  if m.id == body.message_id and m.role == "assistant"), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Message not found")
    async with request.app.state.sessions() as session:
        row = Feedback(conversation_id=body.conversation_id, message_id=body.message_id,
                       user_id=body.user_id, rating=body.rating, comment=body.comment,
                       user_message=history[index - 1].content if index else None,
                       bot_message=history[index].content)
        session.add(row)
        await session.commit()
    metrics.FEEDBACK.labels("up" if body.rating > 0 else "down").inc()
    return {"id": row.id}


# ---------- component-level evaluation endpoints (dev/test only) ----------
def require_debug():
    if not settings.debug_enabled:
        raise HTTPException(status_code=404)


class NLUIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class NLUOut(BaseModel):
    intent: str
    confidence: float
    entities: dict
    source: str
    llm_calls: list[LLMCall]


class RetrieveIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    collection: Literal["knowledge_base", "products"] = "knowledge_base"
    k: int = Field(default=4, ge=1, le=20)


class GuardrailIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    stage: Literal["input", "output"] = "input"
    grounding: str | None = None


@app.post("/eval/nlu", response_model=NLUOut)
async def eval_nlu(body: NLUIn, request: Request):
    """NLU alone (intent accuracy / entity extraction evals)."""
    require_debug()
    trace = Trace()
    result, source = await classify(request.app.state.graph.nlu_chain, body.message, [],
                                    trace.llm_calls)
    return NLUOut(intent=result.intent, confidence=result.confidence,
                  entities=result.entities(), source=source, llm_calls=trace.llm_calls)


@app.post("/eval/retrieve", response_model=list[RetrievedChunk])
async def eval_retrieve(body: RetrieveIn, request: Request):
    """Retriever alone (contextual precision / recall evals, threshold tuning)."""
    require_debug()
    return await request.app.state.retrievers[body.collection].search(body.query, k=body.k)


@app.post("/eval/guardrails", response_model=list[GuardrailResult])
async def eval_guardrails(body: GuardrailIn, request: Request):
    """Guardrails alone (red-team / PII test suites)."""
    require_debug()
    guardrails: Guardrails = request.app.state.guardrails
    if body.stage == "input":
        return (await guardrails.check_input(body.text))[1]
    return guardrails.check_output(body.text, body.grounding)[1]
