"""Tests for the tool-augmented Q&A path (web search + PDF reading) and history."""

from __future__ import annotations

import app.ai.qa as qa_mod
from app.ai.qa import _history_block, answer_question
from app.ai.websearch import SearchResult
from app.models import ExternalIds, Paper, QAResult

SEED = Paper(id="10/seed", title="Seed", external_ids=ExternalIds(doi="10/seed"))


class FakeCodex:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.last_prompt = ""

    def remaining(self):
        return 100

    async def run_structured(self, prompt, schema, *, model=None):
        self.calls += 1
        self.last_prompt = prompt
        return self.payload


def test_history_block():
    assert _history_block([]) == ""
    blk = _history_block([QAResult(question="q1", answer="a1")])
    assert "q1" in blk and "a1" in blk


async def test_answer_with_tools_uses_web_and_pdf(monkeypatch):
    async def fake_search(q, max_results=5):
        return [SearchResult(title="S", url="https://s", snippet="snippet")]

    async def fake_pdf(url, max_chars=4000):
        return "FULL TEXT BODY"

    monkeypatch.setattr(qa_mod, "search", fake_search)
    monkeypatch.setattr(qa_mod, "fetch_pdf_text", fake_pdf)
    papers = [Paper(id="10/a", title="A", pdf_url="https://a.pdf",
                    external_ids=ExternalIds(doi="10/a"))]
    fake = FakeCodex({"answer": "ans", "citations": ["10/a"], "confidence": 0.9})
    res = await answer_question(
        fake, "Q?", SEED, papers, {}, "en",
        use_tools=True, history=[QAResult(question="prev", answer="x")],
    )
    assert res.answer == "ans"
    assert "web" in res.tools_used and "pdf" in res.tools_used
    assert any(s.url == "https://s" for s in res.sources)
    assert "WEB SEARCH RESULTS" in fake.last_prompt
    assert "CONVERSATION SO FAR" in fake.last_prompt


async def test_answer_with_tools_no_results(monkeypatch):
    async def empty_search(q, max_results=5):
        return []

    monkeypatch.setattr(qa_mod, "search", empty_search)
    fake = FakeCodex({"answer": "ans", "citations": [], "confidence": 0.5})
    papers = [Paper(id="10/a", title="A", external_ids=ExternalIds(doi="10/a"))]  # no pdf_url
    res = await answer_question(fake, "Q?", SEED, papers, {}, "en", use_tools=True)
    assert res.tools_used == []  # neither web nor pdf produced evidence


async def test_answer_without_tools_clamps_confidence(monkeypatch):
    fake = FakeCodex({"answer": "a", "citations": [], "confidence": 5.0})
    res = await answer_question(fake, "Q?", SEED, [], {}, "en", use_tools=False)
    assert res.confidence == 1.0
    assert res.tools_used == []
