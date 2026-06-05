"""Codex-powered progressive and final reports over the citation graph."""

from __future__ import annotations

from app.ai.codex_client import CodexClient
from app.ai.relevance import seed_profile
from app.ai.summarize import LANGUAGE_NAMES
from app.models import Paper, Report, ReportCluster

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
