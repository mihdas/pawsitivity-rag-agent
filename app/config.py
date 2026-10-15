"""Central configuration. Everything is read from environment variables (or a .env file)."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"          # answers + topic check
    # Claude Haiku 5.5 rejects temperature/top_p/top_k other than the defaults (400 error), so leave this unset.
    llm_temperature: float | None = None
    llm_max_tokens: int = 2000   # includes possible thinking tokens on Claude 5.5 models

    # Embeddings (run locally inside the container, no extra API key)
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # Vector store
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    collection: str = "pawsitivity_kb"

    # Retrieval
    top_k: int = 4
    min_relevance: float = 0.35   # cosine similarity; below this a chunk counts as "not relevant"

    # API protection
    allowed_origins: str = "https://coexistwithpawsitivity.com,https://www.coexistwithpawsitivity.com"
    rate_limit: str = "20/minute"
    max_message_chars: int = 800
    max_history_turns: int = 6

    # Small-server mode: index knowledge/ inside the API pod at startup instead of a separate ingest job,
    # so the embedding model is only loaded once (saves ~400 MB RAM).
    ingest_on_start: bool = False
    # Retry connecting to Qdrant at startup (it may still be starting after a server reboot)
    ingest_retries: int = 20

    guardrails_file: Path = ROOT / "config" / "guardrails.yaml"
    knowledge_dir: Path = ROOT / "knowledge"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


class GuardrailConfig(BaseModel):
    site_name: str
    assistant_name: str
    scope_description: str
    refusal_message: str
    no_answer_message: str
    blocked_message: str
    greeting_message: str
    injection_patterns: list[str] = []
    blocked_terms: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_guardrails() -> GuardrailConfig:
    data = yaml.safe_load(get_settings().guardrails_file.read_text(encoding="utf-8"))
    return GuardrailConfig(**data)
