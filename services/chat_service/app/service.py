"""Chat orchestration:

    input guardrails -> dialog graph (optionally streaming tokens) -> output guardrails
    -> persist turn + dialog state -> metrics + debug trace
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage

from shared.logging import request_id_var

from . import metrics
from .graph import ChatGraph, Trace
from .guardrails import Guardrails
from .llm import LLMUnavailableError
from .memory import ConversationStore
from .prompts import PROMPT_VERSION, TEMPLATES
from .schemas import ChatRequest, ChatResponse, DebugInfo, DialogState, MessageOut

# Graph nodes whose LLM output is the user-facing reply (NLU tokens are never streamed)
STREAM_NODES = {"products", "order", "my_orders", "policy", "chat", "ask_order_id"}


def to_lc_message(m: MessageOut) -> BaseMessage:
    if m.role == "user":
        return HumanMessage(m.content)
    # Keep what the user saw on cards, so follow-ups ("is the second one in stock?") work
    extra = ""
    if m.products:
        extra = "\n[Products shown: " + "; ".join(
            f"#{p.id} {p.name} ${p.price:.2f} stock {p.stock}" for p in m.products) + "]"
    if m.order:
        extra += f"\n[Order shown: #{m.order.id} status {m.order.status}]"
    return AIMessage(m.content + extra)


class ChatService:
    def __init__(self, graph: ChatGraph, store: ConversationStore, guardrails: Guardrails, *,
                 history_turns: int, primary_provider: str, debug_enabled: bool,
                 callbacks: Callable[[str], list] = lambda request_id: []):
        self._graph = graph
        self._store = store
        self._guardrails = guardrails
        self._history_messages = history_turns * 2  # one turn = user + assistant
        self._primary = primary_provider
        self._debug_enabled = debug_enabled
        self._callbacks = callbacks  # request_id -> LangChain callbacks (Langfuse tracing)

    async def chat(self, request: ChatRequest,
                   on_token: Callable[[str], Any] | None = None) -> ChatResponse:
        started = time.perf_counter()
        conversation_id = request.conversation_id or uuid4().hex
        history = await self._store.history(conversation_id, limit=self._history_messages)
        dialog = await self._store.get_state(conversation_id)
        trace = Trace()

        # 1. Input guardrails: PII masking, prompt injection (never reaches the LLM if blocked)
        safe_message, guards = await self._guardrails.check_input(request.message)
        blocked = next((g for g in guards if g.action == "block"), None)

        if blocked:
            result: dict = {"reply": TEMPLATES["blocked_sensitive" if blocked.name == "pii"
                                                 else "blocked_injection"],
                            "next_dialog": dialog}  # keep any pending question alive
            intent, confidence, nlu_source, entities = "blocked", 1.0, "guardrail", {}
            route = f"blocked:{blocked.name}"
        else:
            state = {"message": safe_message, "user_id": request.user_id, "dialog": dialog,
                     "history": [to_lc_message(m) for m in history], "trace": trace}
            try:
                result = await self._run_graph(state, conversation_id, request, on_token)
            except LLMUnavailableError:
                metrics.LLM_FAILURES.inc()
                raise  # nothing stored; API returns 503
            nlu = result["nlu"]
            intent, confidence, nlu_source = nlu.intent, nlu.confidence, result["nlu_source"]
            entities, route = nlu.entities(), self._graph.route(result)

            # 2. Output guardrails: leaks, sensitive-data requests, ungrounded numbers, PII
            reply, out_guards = self._guardrails.check_output(result["reply"],
                                                              result.get("grounding"))
            guards += out_guards
            if any(g.action == "block" for g in out_guards):
                reply = result.get("fallback_reply") or TEMPLATES["blocked_output"]
            result["reply"] = reply

        bot_msg = MessageOut(
            role="assistant", content=result["reply"],
            products=result.get("products", []), order=result.get("order"),
            sources=result.get("sources", []), suggestions=result.get("suggestions", []),
        )
        # Only the masked user message is ever stored
        await self._store.append(conversation_id,
                                 MessageOut(role="user", content=safe_message), bot_msg)
        await self._store.set_state(conversation_id, result.get("next_dialog", DialogState()))

        debug = DebugInfo(
            request_id=request_id_var.get(),
            prompt_version=PROMPT_VERSION,
            latency_ms=int((time.perf_counter() - started) * 1000),
            intent=intent, confidence=confidence, nlu_source=nlu_source, entities=entities,
            route=route,
            tool_calls=trace.tool_calls,
            llm_calls=trace.llm_calls,
            retrieved_chunks=trace.chunks,
            retrieval_context=[c.content for c in trace.chunks if c.used],
            guardrails=guards,
            fallback_used=any(c.provider != self._primary for c in trace.llm_calls),
            history_messages_used=len(history),
        )
        metrics.record_turn(debug)
        return ChatResponse(conversation_id=conversation_id, message=bot_msg,
                            debug=debug if self._debug_enabled else None)

    async def _run_graph(self, state: dict, conversation_id: str, request: ChatRequest,
                         on_token: Callable[[str], Any] | None) -> dict:
        config = {
            "callbacks": self._callbacks(request_id_var.get()),
            "metadata": {"langfuse_session_id": conversation_id,
                         "langfuse_user_id": str(request.user_id or "guest"),
                         "request_id": request_id_var.get(), "prompt_version": PROMPT_VERSION},
            "run_name": "shopbot-turn",
        }
        if on_token is None:
            return await self._graph.graph.ainvoke(state, config)

        final: dict = {}
        async for mode, chunk in self._graph.graph.astream(state, config,
                                                            stream_mode=["messages", "values"]):
            if mode == "values":
                final = chunk
            else:
                message, meta = chunk
                if (meta.get("langgraph_node") in STREAM_NODES
                        and isinstance(message, AIMessageChunk) and message.content):
                    on_token(str(message.content))
        return final

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[dict]:
        """Server-sent events: token* then final (or error).

        Tokens are streamed before the output guardrails run, so the `final` event carries the
        validated reply and clients must replace the streamed text with it.
        """
        queue: asyncio.Queue[str] = asyncio.Queue()
        task = asyncio.create_task(self.chat(request, on_token=queue.put_nowait))
        while not task.done() or not queue.empty():
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                yield {"type": "token", "text": getter.result()}
            else:
                getter.cancel()
        try:
            response = task.result()
        except LLMUnavailableError:
            yield {"type": "error", "code": "LLM_UNAVAILABLE",
                   "message": "The assistant is temporarily unavailable."}
            return
        except Exception:
            yield {"type": "error", "code": "UPSTREAM_ERROR",
                   "message": "The assistant hit an error. Please try again."}
            raise
        yield {"type": "final", "response": response.model_dump(mode="json")}
