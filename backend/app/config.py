"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="PC_", extra="ignore"
    )

    # --- External data sources ---
    semantic_scholar_api_key: str | None = None
    semantic_scholar_base: str = "https://api.semanticscholar.org/graph/v1"
    openalex_base: str = "https://api.openalex.org"
    openalex_email: str | None = None  # polite pool

    # Politeness / reliability
    s2_min_interval_s: float = 1.1  # ~1 req/s for unauthenticated S2
    openalex_min_interval_s: float = 0.11
    http_timeout_s: float = 30.0
    http_max_retries: int = 4

    # --- Codex ---
    codex_bin: str = "codex"
    codex_model: str | None = None
    codex_concurrency: int = 3
    codex_timeout_s: float = 240.0

    # --- Graph expansion defaults (loose preset) ---
    default_depth: int = 3
    max_depth: int = 5
    per_level_k: int = 80           # top-K kept per level
    relevance_threshold: float = 0.25
    relevance_batch_size: int = 20
    prefilter_per_paper: int = 60   # cheap cap on candidates pulled per frontier paper
    max_candidates_per_level: int = 200  # cap sent to Codex per level (bounds cost)
    summarize_kept: bool = True     # generate per-paper AI summaries for kept nodes

    # --- Global hard ceilings (cost / time guardrails) ---
    max_nodes: int = 600
    max_codex_calls: int = 200

    # --- Storage ---
    db_path: str = "paper_connector.db"

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:24678"]

    @property
    def db_file(self) -> Path:
        return Path(self.db_path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
