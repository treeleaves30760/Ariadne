"""Semantic Scholar Graph API adapter."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.models import Author, Candidate, ExternalIds, Paper
from app.sources.http import HttpFetcher, Throttle
from app.sources.ids import canonical_id, norm_arxiv, norm_doi
from app.storage.db import Database

PAPER_FIELDS = (
    "title,abstract,year,venue,citationCount,fieldsOfStudy,externalIds,authors,tldr,url,"
    "openAccessPdf"
)


class SemanticScholar:
    name = "s2"

    def __init__(self, fetcher: HttpFetcher, settings: Settings):
        self.f = fetcher
        self.base = settings.semantic_scholar_base
        self._headers = (
            {"x-api-key": settings.semantic_scholar_api_key}
            if settings.semantic_scholar_api_key
            else None
        )

    @classmethod
    def build(cls, client: httpx.AsyncClient, settings: Settings, db: Database) -> "SemanticScholar":
        fetcher = HttpFetcher(
            client,
            Throttle(settings.s2_min_interval_s),
            db=db,
            max_retries=settings.http_max_retries,
            source="s2",
        )
        return cls(fetcher, settings)

    # ---------------------------- conversion ----------------------------- #
    @staticmethod
    def _to_paper(raw: dict[str, Any]) -> Paper | None:
        if not raw or not raw.get("title"):
            return None
        ext_raw = raw.get("externalIds") or {}
        ext = ExternalIds(
            doi=norm_doi(ext_raw.get("DOI")),
            arxiv=norm_arxiv(ext_raw.get("ArXiv")),
            s2=raw.get("paperId"),
        )
        if not (ext.doi or ext.s2 or ext.arxiv):
            return None
        tldr = raw.get("tldr") or {}
        return Paper(
            id=canonical_id(ext),
            title=raw["title"],
            abstract=raw.get("abstract"),
            tldr=tldr.get("text") if isinstance(tldr, dict) else None,
            year=raw.get("year"),
            authors=[Author(name=a.get("name", ""), author_id=a.get("authorId"))
                     for a in (raw.get("authors") or []) if a.get("name")],
            venue=raw.get("venue") or None,
            citation_count=raw.get("citationCount"),
            fields_of_study=raw.get("fieldsOfStudy") or [],
            external_ids=ext,
            url=raw.get("url"),
            pdf_url=(raw.get("openAccessPdf") or {}).get("url") if isinstance(raw.get("openAccessPdf"), dict) else None,
            sources=["s2"],
        )

    @staticmethod
    def _path_id(canonical: str, ext: ExternalIds | None = None) -> str:
        """Turn a canonical id (or externalIds) into an S2 path identifier."""
        if ext and ext.s2:
            return ext.s2
        if ext and ext.arxiv:
            # arXiv papers: S2 accepts ARXIV:<id> but 400s on the arXiv DataCite DOI,
            # so prefer the arXiv id whenever we have it (works even for an oa:/DOI canonical).
            return f"ARXIV:{norm_arxiv(ext.arxiv)}"
        if canonical.startswith("s2:"):
            return canonical[3:]
        if canonical.startswith("arxiv:"):
            return f"ARXIV:{canonical[6:]}"
        if canonical.startswith("oa:"):
            return f"DOI:{ext.doi}" if ext and ext.doi else ""  # oa: itself isn't addressable
        return f"DOI:{canonical}"  # canonical was a bare DOI

    # ------------------------------- API --------------------------------- #
    async def search(self, query: str, limit: int = 10) -> list[Candidate]:
        # The keyless public search pool is rate-limited to ~always 429; skip it so
        # it adds neither latency nor noise. OpenAlex + arXiv cover keyless search.
        if self._headers is None:
            return []
        data = await self.f.get_json(
            f"{self.base}/paper/search",
            params={"query": query, "limit": limit, "fields": PAPER_FIELDS},
            headers=self._headers,
            ok_404=True,
        )
        out: list[Candidate] = []
        for raw in (data or {}).get("data", []) or []:
            p = self._to_paper(raw)
            if p:
                out.append(_paper_to_candidate(p))
        return out

    async def batch_lookup(self, ids: list[str]) -> list[dict[str, Any] | None]:
        """One POST /paper/batch for many ids; results are positionally aligned with `ids`.

        Works even without an API key (unlike the search endpoint), so it's used to
        backfill citation counts that OpenAlex/arXiv report as 0/None for recent papers.
        Each id is an S2 path form (a raw paperId, ``ARXIV:<id>`` or ``DOI:<doi>``).
        """
        if not ids:
            return []
        data = await self.f.post_json(
            f"{self.base}/paper/batch",
            {"ids": ids},
            params={"fields": "citationCount,paperId"},
            headers=self._headers,
            max_retries=2,
        )
        return data or []

    async def get_paper(self, canonical: str, ext: ExternalIds | None = None) -> Paper | None:
        pid = self._path_id(canonical, ext)
        if not pid:
            return None
        data = await self.f.get_json(
            f"{self.base}/paper/{pid}", params={"fields": PAPER_FIELDS},
            headers=self._headers, ok_404=True,
        )
        return self._to_paper(data) if data else None

    async def _neighbors(self, canonical: str, kind: str, limit: int,
                         ext: ExternalIds | None = None) -> list[Paper]:
        pid = self._path_id(canonical, ext)
        if not pid:
            return []
        nested = "citedPaper" if kind == "references" else "citingPaper"
        data = await self.f.get_json(
            f"{self.base}/paper/{pid}/{kind}",
            params={"fields": PAPER_FIELDS, "limit": min(limit, 1000)},
            headers=self._headers, ok_404=True,
        )
        out: list[Paper] = []
        for item in (data or {}).get("data", []) or []:
            p = self._to_paper(item.get(nested) or {})
            if p:
                out.append(p)
        return out

    async def get_references(self, canonical: str, limit: int = 200,
                             ext: ExternalIds | None = None) -> list[Paper]:
        return await self._neighbors(canonical, "references", limit, ext)

    async def get_citations(self, canonical: str, limit: int = 200,
                            ext: ExternalIds | None = None) -> list[Paper]:
        return await self._neighbors(canonical, "citations", limit, ext)


def _paper_to_candidate(p: Paper) -> Candidate:
    return Candidate(
        id=p.id,
        title=p.title,
        year=p.year,
        authors=[a.name for a in p.authors[:5]],
        venue=p.venue,
        citation_count=p.citation_count,
        source="s2",
        external_ids=p.external_ids,
    )
