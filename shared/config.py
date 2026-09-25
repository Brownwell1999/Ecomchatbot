"""Central settings, loaded from environment variables (and .env for local runs)."""

from datetime import UTC, datetime
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    # LLM (LangChain chat models)
    llm_provider: str = "ollama"  # groq | ollama | fake
    llm_fallbacks: str = ""
    llm_temperature: float = 0.3
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 60

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    ollama_model: str = "llama3.2:3b"
    ollama_api_base: str = "http://localhost:11434"

    # RAG
    embedding_provider: str = "ollama"  # ollama | fake
    embedding_model: str = "nomic-embed-text"
    rag_top_k: int = 4
    rag_min_score: float = 0.55  # cosine relevance (0..1); below this we say "I don't know"
    # Also drop chunks scoring more than this below the best hit. 0.05 lost recall on an
    # 8-question check ("ship to India?" dropped its answer chunk); 0.10 = 7/8
    rag_score_margin: float = 0.10
    kb_path: str = "data/knowledge_base"

    # Guardrails
    guardrail_classifier: str = "groq"  # groq (Llama Prompt Guard 2) | off
    guardrail_classifier_model: str = "meta-llama/llama-prompt-guard-2-86m"
    guardrail_injection_threshold: float = 0.8
    # Prompt Guard over-flags short commands ("Show my recent orders" = 0.999); on a 23-message
    # check every false positive was <= 4 words and every attack it alone caught was >= 6 words.
    # Short attacks are left to the regex layer.
    guardrail_classifier_min_words: int = 6

    # Production hardening
    rate_limit_per_minute: int = 20  # chat messages per user/IP per minute; 0 = off
    rate_limit_per_day: int = 0  # per user/IP per day (protects the Groq free quota); 0 = off
    demo_mode: bool = False  # public demo: keep the demo-account picker even in prod
    client_ip_header: str = "x-forwarded-for"  # cf-connecting-ip behind a Cloudflare tunnel
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Memory
    redis_url: str = "redis://localhost:6379/0"
    chat_history_turns: int = 10
    chat_session_ttl_seconds: int = 86400

    # Database
    database_url: str = "postgresql+asyncpg://shopbot:shopbot@localhost:5432/shopbot"

    # Service URLs
    chat_service_url: str = "http://localhost:8001"
    catalog_service_url: str = "http://localhost:8002"
    order_service_url: str = "http://localhost:8003"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 120

    # Fixed "today" for deterministic return-window checks, e.g. 2026-09-01T12:00:00
    business_date: datetime | None = None

    @property
    def debug_enabled(self) -> bool:
        """Debug payloads (intent, tools, retrieved chunks...) are exposed outside prod only."""
        return self.app_env in {"dev", "test"}

    @property
    def provider_chain(self) -> list[str]:
        fallbacks = [p.strip() for p in self.llm_fallbacks.split(",") if p.strip()]
        return [self.llm_provider, *[p for p in fallbacks if p != self.llm_provider]]

    @property
    def vector_db_url(self) -> str:
        # langchain-postgres uses psycopg 3, the services use asyncpg
        return self.database_url.replace("+asyncpg", "+psycopg")

    def now(self) -> datetime:
        return self.business_date or datetime.now(UTC).replace(tzinfo=None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
