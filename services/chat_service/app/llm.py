"""LangChain chat models: Groq / Ollama / deterministic fake, chained with `.with_fallbacks()`."""

import logging
import re
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from shared.config import Settings

from .schemas import LLMCall

logger = logging.getLogger("chat_service.llm")

# Test hook: a user message containing this makes the fake model fail (simulated outage)
FAIL_TRIGGER = "__llm_fail__"


class LLMUnavailableError(Exception):
    """Every model in the fallback chain failed."""


class RuleBasedFakeChatModel(BaseChatModel):
    """Deterministic LLM for functional tests and CI: no network, no cost, no flakiness."""

    rules: list[tuple[str, str]] = [
        (r"\b(hi|hello|hey)\b",
         "Hello! I'm ShopBot, your ShopEase shopping assistant. How can I help you today?"),
        (r"\b(bye|goodbye)\b", "Thanks for shopping with ShopEase. Have a great day!"),
        (r"\bthank", "You're welcome! Is there anything else I can help you with?"),
    ]
    default_reply: str = "Here is what I found."

    @property
    def _llm_type(self) -> str:
        return "fake-rules"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        text = str(messages[-1].content)
        if FAIL_TRIGGER in text:
            raise RuntimeError("fake: simulated provider failure")
        reply = next((r for p, r in self.rules if re.search(p, text, re.I)), self.default_reply)
        message = AIMessage(
            content=reply,
            response_metadata={"model_provider": "fake", "model_name": "fake/rule-based-v1"},
            usage_metadata={"input_tokens": sum(len(str(m.content).split()) for m in messages),
                            "output_tokens": len(reply.split()),
                            "total_tokens": 0},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def _chat_model(name: str, s: Settings) -> BaseChatModel:
    match name:
        case "fake":
            return RuleBasedFakeChatModel()
        case "groq":
            if not s.groq_api_key:
                raise ValueError("GROQ_API_KEY is not set")
            extra = {"reasoning_effort": "low"} if "gpt-oss" in s.groq_model else {}
            return ChatGroq(model_name=s.groq_model, api_key=s.groq_api_key,
                            temperature=s.llm_temperature, max_tokens=s.llm_max_tokens,
                            request_timeout=s.llm_timeout_seconds, max_retries=1, **extra)
        case "ollama":
            return ChatOllama(model=s.ollama_model, base_url=s.ollama_api_base,
                              temperature=s.llm_temperature, num_predict=s.llm_max_tokens)
        case _:
            raise ValueError(f"Unknown LLM provider '{name}'")


class LLM:
    """The model chain used by the dialog graph, plus call tracing for debug output."""

    def __init__(self, settings: Settings):
        chain = settings.provider_chain
        self.models = [_chat_model(chain[0], settings)]
        for name in chain[1:]:
            try:
                self.models.append(_chat_model(name, settings))
            except ValueError as exc:
                logger.warning("Skipping fallback provider %s: %s", name, exc)
        self.names = [type(m).__name__ for m in self.models]
        self.chat: Runnable = self.models[0].with_fallbacks(self.models[1:])

    def structured(self, schema: type) -> Runnable | None:
        """Structured-output chain (function calling / JSON schema). None if only fake models."""
        real = [m for m in self.models if not isinstance(m, RuleBasedFakeChatModel)]
        if not real:
            return None
        runnables = [
            m.with_structured_output(
                schema, include_raw=True,
                method="json_schema" if isinstance(m, ChatOllama) else "function_calling")
            for m in real
        ]
        return runnables[0].with_fallbacks(runnables[1:])

    @staticmethod
    async def run(runnable: Runnable, prompt_value: Any, step: str,
                  calls: list[LLMCall]) -> Any:
        """Invoke a chain, record provider/latency/tokens, normalise failures."""
        start = time.perf_counter()
        try:
            result = await runnable.ainvoke(prompt_value)
        except Exception as exc:
            logger.error("LLM chain failed at step %s: %s", step, exc)
            raise LLMUnavailableError(str(exc)) from exc
        raw = result["raw"] if isinstance(result, dict) else result
        meta = getattr(raw, "response_metadata", {}) or {}
        usage = getattr(raw, "usage_metadata", None) or {}
        calls.append(LLMCall(
            step=step,
            provider=meta.get("model_provider", "unknown"),
            model=meta.get("model_name") or meta.get("model") or "unknown",
            latency_ms=int((time.perf_counter() - start) * 1000),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        ))
        return result
