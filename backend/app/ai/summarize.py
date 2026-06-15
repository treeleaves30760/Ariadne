"""Codex-powered short per-paper explanations relative to the seed topic."""

from __future__ import annotations

import asyncio
import logging

from app.ai.codex_client import CodexClient
from app.ai.relevance import seed_profile
from app.models import Paper, Summary

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {"en": "English", "zh": "Traditional Chinese", "bilingual": "Traditional Chinese followed by key English terms in parentheses"}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["paper_id", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def _render(p: Paper) -> str:
    text = (p.abstract or p.tldr or "")[:800]
    return f"- id: {p.id}\n  title: {p.title}\n  abstract: {text}"


def build_prompt(seed: Paper, papers: list[Paper], language: str) -> str:
    lang = LANGUAGE_NAMES.get(language, "English")
    block = "\n".join(_render(p) for p in papers)
    return (
        f"For each paper below, write a 2-3 sentence explanation in {lang} covering: "
        "(1) the problem it tackles, (2) its core method/idea, and (3) how it relates to the "
        "SEED topic. Be specific and useful for a PhD student writing a related-work section.\n\n"
        f"SEED:\n{seed_profile(seed)}\n\n"
        f"PAPERS:\n{block}\n\n"
        "Use the exact paper_id given for each result."
    )


async def summarize_papers(
    codex: CodexClient, seed: Paper, papers: list[Paper], language: str = "en",
    batch_size: int = 12,
) -> list[Summary]:
    """Summarize papers in concurrent batches (Codex's semaphore bounds parallelism)."""
    by_id = {p.id for p in papers}
    batches = [papers[i : i + batch_size] for i in range(0, len(papers), batch_size)]
    log.info("summarizing: %d papers in %d batch(es)", len(papers), len(batches))

    async def run_batch(batch: list[Paper]) -> list[dict]:
        data = await codex.run_structured(build_prompt(seed, batch, language), SUMMARY_SCHEMA)
        return (data or {}).get("results", []) or []

    batched = await asyncio.gather(*(run_batch(b) for b in batches))
    out: list[Summary] = []
    for items in batched:
        for item in items:
            pid = item.get("paper_id")
            if pid in by_id and item.get("summary"):
                out.append(Summary(paper_id=pid, text=item["summary"], language=language))
    return out
