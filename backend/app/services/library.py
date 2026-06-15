"""PaperLibrary: unified access to papers/citations across arXiv + Semantic Scholar + OpenAlex."""

from __future__ import annotations

import asyncio
from typing import Literal

import httpx

from app.config import Settings
from app.models import Candidate, ExternalIds, Paper
from app.sources.arxiv import Arxiv
from app.sources.ids import detect_identifier, normalize_title
from app.sources.merge import collapse_by_title, dedup_candidates, dedup_papers, merge_papers
from app.sources.openalex import OpenAlex
from app.sources.semantic_scholar import SemanticScholar
from app.storage.db import Database

Direction = Literal["reference", "citation"]


async def _safe(coro, default):
    try:
        return await coro
    except Exception:
        return default


async def _bounded(coro, timeout: float):
    """Run a source call under a soft time budget; on timeout the cancel raises
    (caught by the surrounding :func:`_safe`, which yields its default)."""
    return await asyncio.wait_for(coro, timeout)


def _relevance(query: str, title: str) -> float:
    """Score how well a candidate title matches the typed query (higher is better)."""
    q = normalize_title(query)
    t = normalize_title(title)
    if not q or not t:
        return 0.0
    if q == t:
        return 3.0
    if q in t or t in q:
        return 2.0
    qs, ts = set(q.split()), set(t.split())
    return len(qs & ts) / len(qs)


def _cand_from_paper(p: Paper) -> Candidate:
    return Candidate(
        id=p.id,
        title=p.title,
        year=p.year,
        authors=[a.name for a in p.authors[:5]],
        venue=p.venue,
        citation_count=p.citation_count,
        source="+".join(p.sources),
        external_ids=p.external_ids,
    )


class PaperLibrary:
    def __init__(self, client: httpx.AsyncClient, db: Database, settings: Settings):
        self.settings = settings
        self.db = db
        self.s2 = SemanticScholar.build(client, settings, db)
        self.oa = OpenAlex.build(client, settings, db)
        self.ax = Arxiv.build(client, settings, db)

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
        # A query that is itself an arXiv id / DOI resolves straight to that paper.
        ident = detect_identifier(query)
        if ident:
            exact = await self._resolve_identifier(*ident)
            if exact:
                return [exact]

        timeout = self.settings.search_timeout_s
        s2_list, oa_list, ax_list = await asyncio.gather(
            _safe(_bounded(self.s2.search(query, limit), timeout), []),
            _safe(_bounded(self.oa.search(query, limit), timeout), []),
            _safe(_bounded(self.ax.search(query, limit), timeout), []),
        )
        merged = collapse_by_title(dedup_candidates(s2_list, oa_list, ax_list))
        # Backfill citation counts from Semantic Scholar (OpenAlex/arXiv report 0/None
        # for recent papers). One batch call, best-effort so it can't stall or fail search.
        merged = await _safe(_bounded(self._enrich_citations(merged), timeout), merged)
        # Rank by relevance to the typed query first, then citation count, so an
        # exact title match (even a brand-new, 0-citation paper) surfaces on top.
        merged.sort(key=lambda c: (_relevance(query, c.title), c.citation_count or 0),
                    reverse=True)
        return merged[:limit]

    async def _enrich_citations(self, cands: list[Candidate]) -> list[Candidate]:
        """Fill citation counts (and S2 ids) for the candidate list via one S2 batch call."""
        forms: list[tuple[int, str]] = []
        for i, c in enumerate(cands):
            e = c.external_ids
            sid = e.s2 or (f"ARXIV:{e.arxiv}" if e.arxiv else (f"DOI:{e.doi}" if e.doi else None))
            if sid:
                forms.append((i, sid))
        if not forms:
            return cands
        results = await self.s2.batch_lookup([sid for _, sid in forms])
        out = list(cands)
        for (i, _), r in zip(forms, results):
            if not r:
                continue
            update: dict = {}
            cc = r.get("citationCount")
            if isinstance(cc, int) and cc > (out[i].citation_count or 0):
                update["citation_count"] = cc
            pid = r.get("paperId")
            if pid and not out[i].external_ids.s2:
                update["external_ids"] = out[i].external_ids.model_copy(update={"s2": pid})
            if update:
                out[i] = out[i].model_copy(update=update)
        return out

    async def _resolve_identifier(self, kind: str, value: str) -> Candidate | None:
        """Exact lookup for a query that is an arXiv id or DOI."""
        if kind == "arxiv":
            canonical, ext = f"arxiv:{value}", ExternalIds(arxiv=value)
        else:
            canonical, ext = value, ExternalIds(doi=value)
        paper = await _safe(self.get_paper(canonical, ext), None)
        return _cand_from_paper(paper) if paper else None

    # --------------------------- single paper ---------------------------- #
    async def get_paper(self, canonical: str, ext: ExternalIds | None = None) -> Paper | None:
        timeout = self.settings.search_timeout_s
        s2_p, oa_p, ax_p = await asyncio.gather(
            _safe(_bounded(self.s2.get_paper(canonical, ext), timeout), None),
            _safe(_bounded(self.oa.get_paper(canonical, ext), timeout), None),
            _safe(_bounded(self.ax.get_paper(canonical, ext), timeout), None),
        )
        found = [p for p in (s2_p, oa_p, ax_p) if p]
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
