# ShopBot — E-commerce AI Support Chatbot (RAG)

A production-style chatbot for a fictional store (**ShopEase**), built step by step as the
system under test for an **AI test automation framework** (API, UI E2E, LLM evals, RAG evals,
security/red-team, performance).

## Architecture

One-page diagram: [docs/architecture.pdf](docs/architecture.pdf)

```
React UI (5173) ─GraphQL─► Gateway (8000) ─REST/SSE─► chat-service (8001) ──► LLM: Groq ⇢ Ollama (LangChain)
 Presentation   HTTP + WS  API gateway                │  Guardrails (input + output)
                (streaming)JWT auth, rate limiting,   │  NLU (structured output)
                           validation, query limits   │  Dialog manager (LangGraph)
                                                      │  RAG retriever (PGVector) ─► Postgres + pgvector
                                                      │  Memory ─► Redis
                                                      ├─REST─► catalog-service (8002) ─► Postgres
                                                      └─REST─► order-service (8003)   ─► Postgres
```

| Layer | Tech |
|---|---|
| Presentation | React 19 + Vite + TypeScript + Apollo Client; product/order cards, citations, quick replies |
| API gateway | FastAPI + Strawberry GraphQL: JWT login, input validation, depth/alias/token limits, request IDs |
| Microservices | chat-service (LangChain + LangGraph), catalog-service, order-service (FastAPI) |
| Data & AI | PostgreSQL 16 + pgvector, Redis 7, Groq `openai/gpt-oss-20b` with Ollama `llama3.2:3b` fallback, `nomic-embed-text` embeddings |
| Infra & monitoring | Docker Compose, Prometheus + Grafana dashboard, optional Langfuse LLM tracing, JSON logs with `X-Request-ID` across services, GitHub Actions CI |

## How a message is handled (chat-service)

```
input guardrails ─ block ─► safe template (LLM never sees the message)
      │ pass (PII masked)
      ▼
message → understand (NLU) ──route──► products     keyword search → semantic (vector) fallback
                                      order        get_order tool → order card
                                      my_orders    list_orders tool
                                      return       eligibility → confirm (yes/no) → create_return
                                      policy       RAG: retrieve chunks → grounded answer + sources
                                      chat         small talk
                                      ask_order_id / need_login / handoff / out_of_scope (templates)
      │
      ▼
output guardrails ─ block ─► node's safe fallback reply (cards still shown)
```

## Guardrails (Phase 4)

| Stage | Guardrail | Action |
|---|---|---|
| input | PII: credit card (Luhn-validated), CVV, SSN | **block** + security warning; stored/logged masked |
| input | PII: email, phone | **mask** before the LLM, memory and traces |
| input | Prompt injection / jailbreak regex (deterministic, 1 ms) | **block** |
| input | Llama Prompt Guard 2 classifier via Groq (score ≥ `GUARDRAIL_INJECTION_THRESHOLD`) | **block** (fails open if unavailable) |
| output | System-prompt leak (distinctive prompt sentences in the reply) | **block** → safe fallback |
| output | Reply asks for card number / CVV / password | **block** → safe fallback |
| output | Grounding: every number in the reply must appear in tool data / RAG context | **block** → safe fallback |
| output | PII not present in the grounding data | **mask** |

## Production hardening (Phase 5)

| Feature | Where |
|---|---|
| Token streaming | chat-service `POST /chat/stream` (SSE) → GraphQL subscription `sendMessageStream` (graphql-ws) → UI. The `final` event carries the guardrail-validated reply, which replaces the streamed text |
| Rate limiting | Gateway, Redis fixed window per user/IP (`RATE_LIMIT_PER_MINUTE`, 0 = off) → `RATE_LIMITED` + `retryAfterSeconds` |
| Metrics | `/metrics` on every service; Prometheus :9090; Grafana :3000 (dashboard *ShopBot — AI chatbot*): turns by intent, p95 latency, LLM latency/tokens, RAG relevance & no-answer rate, guardrail triggers, fallbacks, errors, feedback |
| LLM tracing | Langfuse (set `LANGFUSE_PUBLIC_KEY/SECRET_KEY`); trace id = `debug.requestId`, session = conversation id |
| Feedback | 👍/👎 → `submitFeedback` → Postgres `feedback` table with the question/answer snapshot |
| Resilience | LLM fallback chain, timeouts + retries, readiness checks (`/ready`: Redis + Postgres), typed errors |
| CI | `.github/workflows/ci.yml`: ruff + unit checks, UI build, dockerised smoke test in offline fake mode |

## LangChain / LangGraph components

| Concern | LangChain / LangGraph component |
|---|---|
| LLM integration + fallback | `ChatGroq`, `ChatOllama`, `.with_fallbacks()` |
| Prompts | `ChatPromptTemplate` + `MessagesPlaceholder` (versioned: `PROMPT_VERSION`) |
| NLU | `.with_structured_output(NLUResult)` (function calling / JSON schema) + regex fallback |
| Tools | `@tool` wrappers over catalog/order services, bound per request to the signed-in user |
| Dialog management | LangGraph `StateGraph` + slot filling / confirmation state in Redis |
| Chunking | `MarkdownHeaderTextSplitter` → `RecursiveCharacterTextSplitter` (600 chars, 80 overlap) + contextual headers |
| Embeddings | `OllamaEmbeddings` (`nomic-embed-text`, with `search_query:` / `search_document:` prefixes) |
| Vector DB | `PGVector` (langchain-postgres): collections `knowledge_base` (33 chunks) and `products` (192) |
| Retrieval | cosine relevance scores, absolute threshold (`RAG_MIN_SCORE`) + relative margin (`RAG_SCORE_MARGIN`) |

## Run it

```bash
cp .env.example .env                 # add GROQ_API_KEY (free) or set LLM_PROVIDER=ollama
docker compose up -d --build         # first run also pulls Ollama models (~2.3 GB)
docker compose run --rm seed         # schema + deterministic demo data
docker compose run --rm ingest       # chunk + embed knowledge base and products into pgvector
```

| URL | What |
|---|---|
| http://localhost:5173 | Chat UI (sign in with a demo customer, password `demo123`) |
| http://localhost:8000/graphql | GraphiQL playground (dev/test only) |
| http://localhost:8001/docs · 8002/docs · 8003/docs | chat / catalog / order service OpenAPI |
| http://localhost:3000 | Grafana dashboard (anonymous view; admin/admin to edit) |
| http://localhost:9090 | Prometheus |

**Public deployment** ([docs/DEPLOY.md](docs/DEPLOY.md)), same hardened prod mode either way:
`./deploy.sh tunnel` shares this machine through a free Cloudflare quick tunnel (no open ports),
`./deploy.sh` runs on a server with your domain and automatic HTTPS (Caddy).

Try: "Show me running shoes under $100" → "Is the cheapest one in stock?" · "I need something to
keep my coffee hot" · "Where is my order?" · "Return this order" → "yes" · "What is your return
policy for electronics?" · "Do you offer student discounts?" (should say it doesn't know).

## Building the DeepEval / pytest framework on this (Phase 6)

Every chat reply (dev/test) carries what DeepEval test cases need:

| DeepEval field | Source |
|---|---|
| `LLMTestCase.input` | the message you send |
| `actual_output` | `message.content` |
| `retrieval_context` | `debug.retrievalContext` (text of the chunks the answer was grounded on) |
| `tools_called` | `debug.toolCalls` → `ToolCall(name, input_parameters=args, output=output)` |
| `ConversationalTestCase` turns | same `conversationId` across calls (memory + dialog state in Redis) |
| extra assertions | `debug.intent/entities/route/guardrails/llmCalls/retrievedChunks/fallbackUsed/latencyMs` |

Component-level endpoints (chat-service, dev/test only) let you evaluate one stage at a time:
`POST /eval/nlu` (intent accuracy), `POST /eval/retrieve` (contextual precision/recall, threshold
tuning), `POST /eval/guardrails` (red-team & PII suites).

Deterministic runs: `LLM_PROVIDER=fake`, `EMBEDDING_PROVIDER=fake`, `GUARDRAIL_CLASSIFIER=off`,
`RATE_LIMIT_PER_MINUTE=0`, fixed `BUSINESS_DATE`, `docker compose run --rm seed` to reset data.
`scripts/smoke_test.py` shows the minimal GraphQL client calls.

## Testability hooks (built in on purpose)
- `debug` on every reply (dev/test): intent, confidence, NLU source, entities, route, tool calls,
  LLM calls (provider, model, latency, tokens), **retrieved chunks with scores and used/rejected**,
  fallback flag, prompt version, request ID.
- `LLM_PROVIDER=fake` + `EMBEDDING_PROVIDER=fake`: deterministic, offline, free. `__llm_fail__` in a
  message simulates an LLM outage.
- `BUSINESS_DATE`: fixed "today" so return-window results are reproducible.
- Deterministic seed data (fixed seeds), stable chunk IDs (`return_policy.md#0`), `data-testid`s in the UI.
- Typed GraphQL error codes: `BAD_USER_INPUT`, `UNAUTHENTICATED`, `LLM_UNAVAILABLE`, `UPSTREAM_*`.

## Roadmap
- [x] Phase 0: foundation, seed data, knowledge base docs
- [x] Phase 1: basic chatbot
- [x] Phase 2: NLU, LangGraph dialog, catalog/order services, JWT auth, returns
- [x] Phase 3: RAG (chunking, embeddings, pgvector, retrieval thresholds, citations) + semantic product search
- [x] Phase 4: guardrails (PII, prompt injection + Prompt Guard classifier, output grounding/leak checks)
- [x] Phase 5: streaming, Langfuse tracing, Prometheus/Grafana, rate limiting, feedback, CI
- [ ] Phase 6: test automation framework (pytest, Playwright, DeepEval, Ragas, Locust)
