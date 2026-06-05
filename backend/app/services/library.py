"""PaperLibrary: unified access to papers/citations across Semantic Scholar + OpenAlex."""

from __future__ import annotations

import asyncio
from typing import Literal

import httpx

from app.config import Settings
from app.models import Candidate, ExternalIds, Paper
from app.sources.merge import dedup_candidates, dedup_papers, merge_papers
from app.sources.openalex import OpenAlex
from app.sources.semantic_scholar import SemanticScholar
from app.storage.db import Database

Direction = Literal["reference", "citation"]


async def _safe(coro, default):
    try:
        return await coro
    except Exception:
        return default


class PaperLibrary:
    def __init__(self, client: httpx.AsyncClient, db: Database, settings: Settings):
        self.settings = settings
        self.db = db
        self.s2 = SemanticScholar.build(client, settings, db)
        self.oa = OpenAlex.build(client, settings, db)

    @classmethod
    def build(cls, db: Database, settings: Settings) -> "PaperLibrary":
        client = httpx.AsyncClient(timeout=settings.http_timeout_s, follow_redirects=True)
        lib = cls(client, db, settings)
        lib._client = client
        return lib

    async def aclose(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None:
            await client.aclose()

    # ------------------------------ resolve ------------------------------ #
    async def resolve(self, query: str, limit: int = 10) -> list[Candidate]:
        s2_list, oa_list = await asyncio.gather(
            _safe(self.s2.search(query, limit), []),
            _safe(self.oa.search(query, limit), []),
        )
        merged = dedup_candidates(s2_list, oa_list)
        # rank: citation count desc, then presence of DOI
        merged.sort(key=lambda c: (c.citation_count or 0), reverse=True)
        return merged[:limit]

    # --------------------------- single paper ---------------------------- #
    async def get_paper(self, canonical: str, ext: ExternalIds | None = None) -> Paper | None:
        s2_p, oa_p = await asyncio.gather(
            _safe(self.s2.get_paper(canonical, ext), None),
            _safe(self.oa.get_paper(canonical, ext), None),
        )
        found = [p for p in (s2_p, oa_p) if p]
        if not found:
            return None
        paper = merge_papers(found)
        await self.db.upsert_paper(paper)
        return paper

    # ------------------------------ neighbors ---------------------------- #
    async def get_neighbors(
        self, canonical: str, direction: Direction, limit: int, ext: ExternalIds | None = None
    ) -> list[Paper]:
        """Primary source (S2) with OpenAlex fallback; results deduped & cached."""
        kind_s2 = self.s2.get_references if direction == "reference" else self.s2.get_citations
        kind_oa = self.oa.get_references if direction == "reference" else self.oa.get_citations

        papers = await _safe(kind_s2(canonical, limit, ext), [])
        if not papers:
            papers = await _safe(kind_oa(canonical, limit, ext), [])
        merged = dedup_papers(papers)
        for p in merged:
            await self.db.upsert_paper(p)
        return merged
