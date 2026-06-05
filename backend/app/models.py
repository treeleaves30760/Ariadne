"""Domain models (Pydantic) shared across the backend."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Papers
# --------------------------------------------------------------------------- #
class ExternalIds(BaseModel):
    doi: str | None = None
    arxiv: str | None = None
    s2: str | None = None          # Semantic Scholar paperId
    openalex: str | None = None    # OpenAlex work id (Wxxxx)


class Author(BaseModel):
    name: str
    author_id: str | None = None


class Paper(BaseModel):
    """Canonical, source-merged paper record.

    `id` is the canonical key: DOI when available (lowercased, bare), else
    ``s2:<paperId>`` or ``oa:<workId>``.
    """

    id: str
    title: str
    abstract: str | None = None
    tldr: str | None = None
    year: int | None = None
    authors: list[Author] = Field(default_factory=list)
    venue: str | None = None
    citation_count: int | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    url: str | None = None
    sources: list[str] = Field(default_factory=list)  # ["s2", "openalex"]


Direction = Literal["reference", "citation"]


class Edge(BaseModel):
    src: str          # canonical paper id (the citing paper)
    dst: str          # canonical paper id (the cited paper)
    direction: Direction
    level: int        # BFS level at which the edge was discovered


# --------------------------------------------------------------------------- #
# Resolve / search
# --------------------------------------------------------------------------- #
class Candidate(BaseModel):
    id: str
    title: str
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    citation_count: int | None = None
    source: str
    external_ids: ExternalIds = Field(default_factory=ExternalIds)


class ResolveRequest(BaseModel):
    query: str
    limit: int = 10


class ResolveResponse(BaseModel):
    candidates: list[Candidate]


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
class JobStatus(str, Enum):
    queued = "queued"
    resolving = "resolving"
    expanding = "expanding"
    reporting = "reporting"
    completed = "completed"
    failed = "failed"


Language = Literal["en", "zh", "bilingual"]


class JobParams(BaseModel):
    seed_id: str
    depth: int = 3
    language: Language = "en"
    per_level_k: int | None = None
    relevance_threshold: float | None = None
    include_citations: bool = True
    include_references: bool = True


class JobProgress(BaseModel):
    status: JobStatus = JobStatus.queued
    current_level: int = 0
    nodes: int = 0
    edges: int = 0
    codex_calls: int = 0
    message: str = ""
    reports_available: list[str] = Field(default_factory=list)  # ["3","4","5","final"]


class Job(BaseModel):
    id: str
    params: JobParams
    progress: JobProgress = Field(default_factory=JobProgress)
    created_at: str
    error: str | None = None


# --------------------------------------------------------------------------- #
# AI artifacts
# --------------------------------------------------------------------------- #
class RelevanceResult(BaseModel):
    paper_id: str
    relevance: float
    reason: str = ""


class Summary(BaseModel):
    paper_id: str
    text: str
    language: str


class ReportCluster(BaseModel):
    theme: str
    summary: str
    paper_ids: list[str] = Field(default_factory=list)


class Report(BaseModel):
    level: str  # "3" | "4" | "5" | "final"
    overview: str
    clusters: list[ReportCluster] = Field(default_factory=list)
    must_reads: list[str] = Field(default_factory=list)  # paper ids
    gaps: list[str] = Field(default_factory=list)
    raw: dict[str, Any] | None = None
