"""OpenAlex API adapter."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.models import Author, Candidate, ExternalIds, Paper
from app.sources.http import HttpFetcher, Throttle
from app.sources.ids import canonical_id, norm_doi, norm_openalex
from app.storage.db import Database

WORK_SELECT = (
    "id,doi,display_name,publication_year,referenced_works,cited_by_count,"
    "authorships,primary_location,ids,abstract_inverted_index,concepts"
)


def reconstruct_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(w for _, w in positions)


class OpenAlex:
    name = "openalex"

    def __init__(self, fetcher: HttpFetcher, settings: Settings):
        self.f = fetcher
        self.base = settings.openalex_base
        self._mailto = settings.openalex_email

    @classmethod
    def build(cls, client: httpx.AsyncClient, settings: Settings, db: Database) -> "OpenAlex":
        fetcher = HttpFetcher(
            client,
            Throttle(settings.openalex_min_interval_s),
            db=db,
            max_retries=settings.http_max_retries,
            source="openalex",
        )
        return cls(fetcher, settings)

    def _params(self, **extra: Any) -> dict[str, Any]:
        p = dict(extra)
        if self._mailto:
            p["mailto"] = self._mailto
        return p

    @staticmethod
    def _to_paper(raw: dict[str, Any]) -> Paper | None:
        if not raw or not (raw.get("display_name") or raw.get("title")):
            return None
        ids = raw.get("ids") or {}
        ext = ExternalIds(
            doi=norm_doi(raw.get("doi") or ids.get("doi")),
            openalex=norm_openalex(raw.get("id") or ids.get("openalex")),
        )
        if not (ext.doi or ext.openalex):
            return None
        venue = None
        loc = raw.get("primary_location") or {}
        if isinstance(loc, dict) and isinstance(loc.get("source"), dict):
            venue = loc["source"].get("display_name")
        concepts = [c.get("display_name") for c in (raw.get("concepts") or [])[:5]
                    if c.get("display_name")]
        return Paper(
            id=canonical_id(ext),
            title=raw.get("display_name") or raw.get("title"),
            abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
            tldr=None,
            year=raw.get("publication_year"),
            authors=[Author(name=a["author"]["display_name"],
                            author_id=norm_openalex(a["author"].get("id")))
                     for a in (raw.get("authorships") or [])
                     if a.get("author", {}).get("display_name")],
            venue=venue,
            citation_count=raw.get("cited_by_count"),
            fields_of_study=concepts,
            external_ids=ext,
            url=ext.doi and f"https://doi.org/{ext.doi}" or (raw.get("id")),
            sources=["openalex"],
        )

    @staticmethod
    def _oa_path(canonical: str, ext: ExternalIds | None = None) -> str:
        if ext and ext.openalex:
            return norm_openalex(ext.openalex)
        if canonical.startswith("oa:"):
            return canonical[3:]
        if canonical.startswith(("s2:", "arxiv:")):
            return ""  # not directly addressable; use DOI path otherwise
        return f"doi:{canonical}"  # bare DOI

    async def search(self, query: str, limit: int = 10) -> list[Candidate]:
        data = await self.f.get_json(
            f"{self.base}/works",
            params=self._params(search=query, per_page=min(limit, 25), select=WORK_SELECT),
            ok_404=True,
        )
        out: list[Candidate] = []
        for raw in (data or {}).get("results", []) or []:
            p = self._to_paper(raw)
            if p:
                out.append(_paper_to_candidate(p))
        return out

    async def get_paper(self, canonical: str, ext: ExternalIds | None = None) -> Paper | None:
        path = self._oa_path(canonical, ext)
        if not path:
            return None
        data = await self.f.get_json(
            f"{self.base}/works/{path}", params=self._params(select=WORK_SELECT), ok_404=True
        )
        return self._to_paper(data) if data else None

    async def _works_by_ids(self, oa_ids: list[str]) -> list[Paper]:
        out: list[Paper] = []
        for i in range(0, len(oa_ids), 50):
            chunk = oa_ids[i : i + 50]
            data = await self.f.get_json(
                f"{self.base}/works",
                params=self._params(
                    filter=f"openalex_id:{'|'.join(chunk)}", per_page=50, select=WORK_SELECT
                ),
                ok_404=True,
            )
            for raw in (data or {}).get("results", []) or []:
                p = self._to_paper(raw)
                if p:
                    out.append(p)
        return out

    async def get_references(self, canonical: str, limit: int = 200,
                             ext: ExternalIds | None = None) -> list[Paper]:
        paper_raw = await self._raw_work(canonical, ext)
        refs = [norm_openalex(r) for r in (paper_raw or {}).get("referenced_works", [])]
        refs = [r for r in refs if r][:limit]
        return await self._works_by_ids(refs)

    async def get_citations(self, canonical: str, limit: int = 200,
                            ext: ExternalIds | None = None) -> list[Paper]:
        paper_raw = await self._raw_work(canonical, ext)
        oa_id = norm_openalex((paper_raw or {}).get("id"))
        if not oa_id:
            return []
        out: list[Paper] = []
        per_page = 50
        pages = max(1, (limit + per_page - 1) // per_page)
        for page in range(1, pages + 1):
            data = await self.f.get_json(
                f"{self.base}/works",
                params=self._params(
                    filter=f"cites:{oa_id}", per_page=per_page, page=page, select=WORK_SELECT
                ),
                ok_404=True,
            )
            results = (data or {}).get("results", []) or []
            if not results:
                break
            for raw in results:
                p = self._to_paper(raw)
                if p:
                    out.append(p)
        return out[:limit]

    async def _raw_work(self, canonical: str, ext: ExternalIds | None = None) -> dict | None:
        path = self._oa_path(canonical, ext)
        if not path:
            return None
        return await self.f.get_json(
            f"{self.base}/works/{path}", params=self._params(select=WORK_SELECT), ok_404=True
        )


def _paper_to_candidate(p: Paper) -> Candidate:
    return Candidate(
        id=p.id,
        title=p.title,
        year=p.year,
        authors=[a.name for a in p.authors[:5]],
        venue=p.venue,
        citation_count=p.citation_count,
        source="openalex",
        external_ids=p.external_ids,
    )
