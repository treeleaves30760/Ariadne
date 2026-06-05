"""Grounded Q&A over the collected corpus — "ask this literature".

Answers a student's question using only the papers collected for a job, with
citations back to specific paper ids so the answer is verifiable.
"""

from __future__ import annotations

from app.ai.codex_client import CodexClient
from app.ai.relevance import seed_profile
from app.ai.report import _resolve_ids
from app.ai.summarize import LANGUAGE_NAMES
from app.models import Paper, QAResult

QA_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["answer", "citations", "confidence"],
    "additionalProperties": False,
}


def _render(p: Paper, summary: str | None) -> str:
    yr = f" ({p.year})" if p.year else ""
    text = summary or p.tldr or (p.abstract or "")[:400]
    return f"- id: {p.id} | {p.title}{yr}\n  {text}"


def build_prompt(question: str, seed: Paper, papers: list[Paper],
                 summaries: dict[str, str], language: str) -> str:
    lang = LANGUAGE_NAMES.get(language, "English")
    block = "\n".join(_render(p, summaries.get(p.id)) for p in papers)
    return (
        "You are a research assistant helping a PhD student understand a body of literature. "
        f"Answer the QUESTION using ONLY the papers in the CORPUS below. Answer in the same "
        f"language as the question (otherwise {lang}). Be specific and synthesize across papers; "
        "if the corpus does not contain enough information, say so plainly rather than guessing. "
        "Cite the exact paper_id of every paper you rely on in `citations`, and give a calibrated "
        "`confidence` in [0,1].\n\n"
        f"SEED TOPIC:\n{seed_profile(seed)}\n\n"
        f"CORPUS ({len(papers)} papers):\n{block}\n\n"
        f"QUESTION: {question}"
    )


async def answer_question(
    codex: CodexClient,
    question: str,
    seed: Paper,
    papers: list[Paper],
    summaries: dict[str, str],
    language: str = "en",
) -> QAResult:
    prompt = build_prompt(question, seed, papers, summaries, language)
    data = await codex.run_structured(prompt, QA_SCHEMA)
    data = data or {}
    valid = {p.id for p in papers}
    conf = float(data.get("confidence", 0.0) or 0.0)
    return QAResult(
        question=question,
        answer=data.get("answer", ""),
        citations=_resolve_ids(data.get("citations", []), valid),
        confidence=max(0.0, min(1.0, conf)),
    )
