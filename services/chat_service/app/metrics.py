"""Chatbot-specific Prometheus metrics (LLM, RAG, guardrails, NLU, feedback)."""

from prometheus_client import Counter, Histogram

from .schemas import DebugInfo

CHAT_TURNS = Counter("chat_turns_total", "Chat turns", ["intent", "route", "blocked"])
LLM_CALLS = Counter("llm_calls_total", "LLM calls", ["provider", "model", "step"])
LLM_LATENCY = Histogram("llm_latency_seconds", "LLM call latency", ["provider", "step"],
                        buckets=(0.25, 0.5, 1, 2, 3, 5, 10, 20, 40))
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens", ["provider", "direction"])
LLM_FAILURES = Counter("llm_unavailable_total", "Turns where every LLM in the chain failed")
FALLBACKS = Counter("llm_fallback_total", "Turns served (partly) by a fallback model")
RAG_TOP_SCORE = Histogram("rag_top_score", "Relevance score of the best retrieved chunk",
                          ["collection"], buckets=(0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9))
RAG_CHUNKS_USED = Histogram("rag_chunks_used", "Chunks passed to the prompt", ["collection"],
                            buckets=(0, 1, 2, 3, 4, 6))
GUARDRAILS = Counter("guardrail_triggers_total", "Guardrail results that did not pass",
                     ["name", "stage", "action"])
FEEDBACK = Counter("chat_feedback_total", "User feedback on replies", ["rating"])


def record_turn(d: DebugInfo) -> None:
    CHAT_TURNS.labels(d.intent, d.route, str(d.intent == "blocked").lower()).inc()
    for c in d.llm_calls:
        LLM_CALLS.labels(c.provider, c.model, c.step).inc()
        LLM_LATENCY.labels(c.provider, c.step).observe(c.latency_ms / 1000)
        LLM_TOKENS.labels(c.provider, "input").inc(c.input_tokens or 0)
        LLM_TOKENS.labels(c.provider, "output").inc(c.output_tokens or 0)
    if d.fallback_used:
        FALLBACKS.inc()
    by_collection: dict[str, list] = {}
    for chunk in d.retrieved_chunks:
        by_collection.setdefault(chunk.collection, []).append(chunk)
    for collection, chunks in by_collection.items():
        RAG_TOP_SCORE.labels(collection).observe(max(c.score for c in chunks))
        RAG_CHUNKS_USED.labels(collection).observe(sum(c.used for c in chunks))
    for g in d.guardrails:
        if not g.passed:
            GUARDRAILS.labels(g.name, g.stage, g.action).inc()
