"""Codex-powered progressive and final reports over the citation graph."""

from __future__ import annotations

from app.ai.codex_client import CodexClient
from app.ai.relevance import seed_profile
from app.ai.summarize import LANGUAGE_NAMES
from app.ai.websearch import SearchResult, search_many
from app.models import Paper, Report, ReportCluster, WebSource

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "summary": {"type": "string"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["theme", "summary", "paper_ids"],
                "additionalProperties": False,
            },
        },
        "must_reads": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overview", "clusters", "must_reads", "gaps"],
    "additionalProperties": False,
}


def _render(p: Paper, summary: str | None) -> str:
    yr = f" ({p.year})" if p.year else ""
    s = summary or p.tldr or (p.abstract or "")[:200]
    return f"- id: {p.id} | {p.title}{yr}\n  {s}"


def build_prompt(
    seed: Paper, papers: list[Paper], summaries: dict[str, str], level: str, language: str
) -> str:
    lang = LANGUAGE_NAMES.get(language, "English")
    block = "\n".join(_render(p, summaries.get(p.id)) for p in papers)
    if level == "final":
        scope = (
            "This is the FINAL synthesis across the entire citation graph. Provide a thorough "
            "overview, group papers by solution approach / theme, recommend a reading order via "
            "must_reads (most foundational first), and identify open research gaps/directions."
        )
    else:
        scope = (
            f"This is a progressive report after expanding to depth {level}. Summarize what the "
            "literature collected so far covers, group papers by solution approach / theme, list "
            "the most important must_reads, and note gaps to watch as expansion continues."
        )
    return (
        f"You are writing a literature-map report in {lang} for a PhD student.\n{scope}\n\n"
        f"SEED:\n{seed_profile(seed)}\n\n"
        f"PAPERS ({len(papers)}):\n{block}\n\n"
        "Cluster every paper into a theme (each paper_id should appear in exactly one cluster, "
        "using the exact ids given). must_reads and gaps should be concise. "
        "The overview should be a few sentences of prose."
    )


def _match_id(value: str, valid: set[str]) -> str | None:
    """Map a model-returned reference back to a real paper id.

    The model is asked for bare ids but sometimes returns "id — title" or similar;
    accept an exact match, else a valid id contained in the returned string.
    """
    if value in valid:
        return value
    candidates = [vid for vid in valid if vid in value]
    if candidates:
        return max(candidates, key=len)  # longest match wins (avoids prefix collisions)
    return None


def _resolve_ids(values: list[str], valid: set[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        m = _match_id(v, valid)
        if m and m not in out:
            out.append(m)
    return out


async def generate_report(
    codex: CodexClient,
    seed: Paper,
    papers: list[Paper],
    summaries: dict[str, str],
    level: str,
    language: str = "en",
) -> Report:
    prompt = build_prompt(seed, papers, summaries, level, language)
    data = await codex.run_structured(prompt, REPORT_SCHEMA)
    data = data or {}
    valid = {p.id for p in papers}
    clusters = [
        ReportCluster(
            theme=c.get("theme", ""),
            summary=c.get("summary", ""),
            paper_ids=_resolve_ids(c.get("paper_ids", []), valid),
        )
        for c in data.get("clusters", [])
    ]
    return Report(
        level=level,
        overview=data.get("overview", ""),
        clusters=clusters,
        must_reads=_resolve_ids(data.get("must_reads", []), valid),
        gaps=data.get("gaps", []),
        raw=data,
    )


WEB_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["title", "url", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "sources"],
    "additionalProperties": False,
}


def _web_queries(seed: Paper, gaps: list[str], max_queries: int) -> list[str]:
    base = [seed.title, f"{seed.title} survey", f"{seed.title} recent advances"]
    for g in gaps:
        base.append(g if len(g) < 90 else g[:90])
    return base[:max_queries]


async def generate_web_context(
    codex: CodexClient,
    seed: Paper,
    gaps: list[str],
    *,
    language: str = "en",
    max_results: int = 5,
    max_queries: int = 6,
) -> Report:
    """Search the web (DuckDuckGo) and synthesize an external-context report.

    Surfaces surveys / recent / follow-up work that may not be in the citation graph.
    """
    queries = _web_queries(seed, gaps, max_queries)
    results = await search_many(queries, max_results)
    if not results:
        return Report(level="web", overview="No external web results were found.", sources=[])

    by_url = {r.url: r for r in results}
    lang = LANGUAGE_NAMES.get(language, "English")
    block = "\n".join(f"- {r.title}\n  url: {r.url}\n  {r.snippet[:300]}" for r in results)
    prompt = (
        f"You are extending a literature report with EXTERNAL web context, in {lang}. "
        "Below are web search results related to the seed topic (these are NOT from the "
        "citation graph). Write a concise synthesis of what additional/recent/related work "
        "they reveal — surveys, follow-up directions, tools, or perspectives that complement "
        "the citation graph — and select the most useful sources with a one-line note each. "
        "Only use URLs that appear in the list; do not invent sources.\n\n"
        f"SEED:\n{seed_profile(seed)}\n\n"
        f"WEB RESULTS:\n{block}\n"
    )
    data = await codex.run_structured(prompt, WEB_REPORT_SCHEMA)
    data = data or {}
    sources: list[WebSource] = []
    for s in data.get("sources", []):
        url = s.get("url", "")
        real = by_url.get(url)
        if real is None:  # tolerate trailing slashes / minor mismatch
            real = next((r for r in results if r.url.rstrip("/") == url.rstrip("/")), None)
        if real:
            sources.append(WebSource(title=real.title, url=real.url, note=s.get("note", "")))
    # fall back to raw results if the model returned none
    if not sources:
        sources = [WebSource(title=r.title, url=r.url, note=r.snippet[:140]) for r in results[:max_results]]
    return Report(level="web", overview=data.get("overview", ""), sources=sources, raw=data)
