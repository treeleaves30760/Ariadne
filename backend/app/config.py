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

    # arXiv direct source — covers very recent papers and arXiv-id / DOI lookups
    # that Semantic Scholar / OpenAlex haven't indexed yet.
    arxiv_base: str = "https://export.arxiv.org/api"
    arxiv_min_interval_s: float = 3.0  # arXiv asks for ~1 request / 3s

    # Interactive resolve: soft per-source time budget so one slow or dead source
    # (e.g. rate-limited, keyless Semantic Scholar) can't stall the whole search.
    search_timeout_s: float = 8.0

    # Logging verbosity for the `app` logger namespace (DEBUG/INFO/WARNING/...).
    log_level: str = "INFO"

    # --- Web search (DuckDuckGo) for report enrichment ---
    web_search_enabled: bool = True
    web_search_max_results: int = 5
    web_search_max_queries: int = 6

    # --- Codex ---
    codex_bin: str = "codex"
    codex_model: str | None = None
    codex_concurrency: int = 3
    codex_timeout_s: float = 240.0
    codex_bypass_sandbox: bool = False  # PC_CODEX_BYPASS_SANDBOX; set 1 in containers

    # --- Graph expansion defaults (loose preset) ---
    default_depth: int = 3
    max_depth: int = 5
    per_level_k: int = 80           # top-K kept per level
    relevance_threshold: float = 0.25
    relevance_batch_size: int = 20
    prefilter_per_paper: int = 60   # cheap cap on candidates pulled per frontier paper
    max_candidates_per_level: int = 200  # cap sent to Codex per level (bounds cost)
    summarize_kept: bool = True     # generate per-paper AI summaries for kept nodes

    # --- Cross-linking: discover citation edges *among* the kept papers ---
    # Without this the map is a star (only seed→paper). Cross-linking fetches the
    # references of kept papers and connects any pair that are both in the map,
    # revealing inter-paper structure and which works are foundational (high in-degree).
    cross_link_enabled: bool = True
    cross_link_max_nodes: int = 300  # cap on extra reference fetches (cost guardrail)

    # --- Global hard ceilings (cost / time guardrails) ---
    max_nodes: int = 600
    max_codex_calls: int = 200

    # --- Storage ---
    db_path: str = "paper_connector.db"

    # --- CORS ---
    # Explicit dev origins; the regex below also covers any localhost/127.0.0.1 port,
    # so the page works whether opened via localhost:3000 or 127.0.0.1:3000.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:24678",
        "http://127.0.0.1:24678",
    ]
    cors_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    @property
    def db_file(self) -> Path:
        return Path(self.db_path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
