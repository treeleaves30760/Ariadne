"""Grounded, tool-augmented, multi-turn Q&A over the collected corpus.

"Ask this literature": answers a student's question using the collected papers,
optionally calling tools (web search + reading open-access PDFs) to verify and
deepen the answer, and carrying short conversation history for follow-ups.
"""

from __future__ import annotations

from app.ai.codex_client import CodexClient
from app.ai.relevance import seed_profile
from app.ai.report import _resolve_ids
from app.ai.summarize import LANGUAGE_NAMES
from app.ai.websearch import search
from app.models import Paper, QAResult, WebSource
from app.sources.fulltext import fetch_pdf_text

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


def _history_block(history: list[QAResult], limit: int = 3) -> str:
    if not history:
        return ""
    recent = history[-limit:]
    turns = "\n".join(f"Q: {h.question}\nA: {h.answer}" for h in recent)
    return f"\nCONVERSATION SO FAR (for follow-up context):\n{turns}\n"


async def _gather_tools(
    question: str, seed: Paper, papers: list[Paper], web_max: int
) -> tuple[str, list[WebSource], list[str]]:
    """Run web search + read up to 2 relevant open-access PDFs. Returns (block, sources, used)."""
    used: list[str] = []
    sources: list[WebSource] = []
    chunks: list[str] = []

    # web search
    web = await search(f"{seed.title} {question}", max_results=web_max)
    if web:
        used.append("web")
        sources.extend(WebSource(title=r.title, url=r.url, note=r.snippet[:160]) for r in web)
        chunks.append(
            "WEB SEARCH RESULTS:\n"
            + "\n".join(f"- {r.title} ({r.url})\n  {r.snippet[:240]}" for r in web)
        )

    # read PDFs of the most relevant papers that have an open-access PDF
    with_pdf = [p for p in papers if p.pdf_url][:2]
    pdf_texts = []
    for p in with_pdf:
        text = await fetch_pdf_text(p.pdf_url, max_chars=4000)
        if text:
            pdf_texts.append(f"FULL TEXT EXCERPT — {p.title} (id: {p.id}):\n{text[:4000]}")
            sources.append(WebSource(title=f"PDF: {p.title}", url=p.pdf_url or "", note="full-text excerpt"))
    if pdf_texts:
        used.append("pdf")
        chunks.append("\n\n".join(pdf_texts))

    return ("\n\n".join(chunks), sources, used)


def build_prompt(
    question: str, seed: Paper, papers: list[Paper], summaries: dict[str, str],
    language: str, history: list[QAResult], tool_block: str,
) -> str:
    lang = LANGUAGE_NAMES.get(language, "English")
    corpus = "\n".join(_render(p, summaries.get(p.id)) for p in papers)
    tools = f"\nADDITIONAL EVIDENCE FROM TOOLS (web search / PDF reading):\n{tool_block}\n" if tool_block else ""
    return (
        "You are a research assistant helping a PhD student understand a body of literature. "
        "Answer the QUESTION primarily from the CORPUS; you MAY use the ADDITIONAL EVIDENCE "
        "to verify, add recent context, or fill gaps. Answer in the same language as the "
        f"question (otherwise {lang}). Synthesize across papers, be specific, and if the "
        "evidence is insufficient say so rather than guessing. Cite the exact paper_id of "
        "every corpus paper you rely on in `citations`, and give a calibrated `confidence` "
        "in [0,1].\n\n"
        f"SEED TOPIC:\n{seed_profile(seed)}\n"
        f"{_history_block(history)}"
        f"\nCORPUS ({len(papers)} papers):\n{corpus}\n"
        f"{tools}\n"
        f"QUESTION: {question}"
    )


async def answer_question(
    codex: CodexClient,
    question: str,
    seed: Paper,
    papers: list[Paper],
    summaries: dict[str, str],
    language: str = "en",
    *,
    history: list[QAResult] | None = None,
    use_tools: bool = False,
    web_max: int = 5,
) -> QAResult:
    history = history or []
    tool_block, sources, used = ("", [], [])
    if use_tools:
        tool_block, sources, used = await _gather_tools(question, seed, papers, web_max)

    prompt = build_prompt(question, seed, papers, summaries, language, history, tool_block)
    data = await codex.run_structured(prompt, QA_SCHEMA)
    data = data or {}
    valid = {p.id for p in papers}
    conf = float(data.get("confidence", 0.0) or 0.0)
    return QAResult(
        question=question,
        answer=data.get("answer", ""),
        citations=_resolve_ids(data.get("citations", []), valid),
        confidence=max(0.0, min(1.0, conf)),
        sources=sources,
        tools_used=used,
    )
