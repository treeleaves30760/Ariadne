"""DuckDuckGo web search — lets the system reach beyond the citation graph.

Used to enrich reports with external/recent context (surveys, blog posts,
follow-up work) that may not appear in the seed paper's citations.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


def _search_sync(query: str, max_results: int) -> list[SearchResult]:
    try:
        from ddgs import DDGS
    except Exception:
        return []
    out: list[SearchResult] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                url = r.get("href") or r.get("url") or ""
                title = r.get("title") or ""
                body = r.get("body") or r.get("snippet") or ""
                if url and title:
                    out.append(SearchResult(title=title, url=url, snippet=body))
    except Exception:
        return out
    return out


async def search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Run a DuckDuckGo text search off the event loop. Never raises."""
    return await asyncio.to_thread(_search_sync, query, max_results)


async def search_many(queries: list[str], max_results: int = 5) -> list[SearchResult]:
    """Run several searches concurrently and dedup results by URL."""
    batches = await asyncio.gather(*(search(q, max_results) for q in queries))
    seen: set[str] = set()
    merged: list[SearchResult] = []
    for batch in batches:
        for r in batch:
            if r.url not in seen:
                seen.add(r.url)
                merged.append(r)
    return merged
