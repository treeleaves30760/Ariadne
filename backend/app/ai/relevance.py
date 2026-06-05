"""Codex-powered relevance scoring of candidate papers against a seed topic."""

from __future__ import annotations

from app.ai.codex_client import CodexClient
from app.models import Paper, RelevanceResult

RELEVANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "relevance": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["paper_id", "relevance", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def seed_profile(seed: Paper) -> str:
    parts = [f"Title: {seed.title}"]
    if seed.year:
        parts.append(f"Year: {seed.year}")
    text = seed.abstract or seed.tldr
    if text:
        parts.append(f"Abstract: {text[:1500]}")
    if seed.fields_of_study:
        parts.append(f"Fields: {', '.join(seed.fields_of_study)}")
    return "\n".join(parts)


def _render_candidate(p: Paper) -> str:
    text = (p.tldr or p.abstract or "")[:500]
    yr = f" ({p.year})" if p.year else ""
    return f"- id: {p.id}\n  title: {p.title}{yr}\n  summary: {text}"


def build_prompt(seed: Paper, candidates: list[Paper]) -> str:
    cand_block = "\n".join(_render_candidate(p) for p in candidates)
    return (
        "You are assisting a PhD student in building a literature map. Given a SEED paper "
        "and a list of CANDIDATE papers (drawn from the seed's references and citations), "
        "rate how relevant each candidate is for understanding, comparing against, or building "
        "on the seed topic.\n\n"
        "Scoring guidance (be generous / inclusive — err toward keeping borderline papers):\n"
        "  1.0 = directly addresses the same problem or is a core method/baseline\n"
        "  0.6 = clearly related sub-problem, dataset, or technique\n"
        "  0.3 = tangentially related (shared domain or background)\n"
        "  0.0 = unrelated\n\n"
        f"SEED:\n{seed_profile(seed)}\n\n"
        f"CANDIDATES:\n{cand_block}\n\n"
        "Return one result per candidate using the exact paper_id given. "
        "Each reason must be a single concise sentence."
    )


async def score_relevance(
    codex: CodexClient, seed: Paper, candidates: list[Paper], batch_size: int = 20
) -> list[RelevanceResult]:
    """Score candidates in batches; returns one RelevanceResult per scored candidate."""
    results: list[RelevanceResult] = []
    by_id = {p.id: p for p in candidates}
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        prompt = build_prompt(seed, batch)
        data = await codex.run_structured(prompt, RELEVANCE_SCHEMA)
        for item in (data or {}).get("results", []):
            pid = item.get("paper_id")
            if pid in by_id:
                results.append(
                    RelevanceResult(
                        paper_id=pid,
                        relevance=float(max(0.0, min(1.0, item.get("relevance", 0.0)))),
                        reason=item.get("reason", ""),
                    )
                )
    return results
