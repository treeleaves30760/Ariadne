"""Tests for grounded Q&A and web-context report generation (mocked Codex/web)."""

from __future__ import annotations

import app.ai.report as report_mod
from app.ai.qa import answer_question
from app.ai.report import generate_web_context
from app.ai.websearch import SearchResult
from app.models import ExternalIds, Paper


class FakeCodex:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    @property
    def calls_count(self):
        return self.calls

    def remaining(self):
        return 100

    async def run_structured(self, prompt, schema, *, model=None):
        self.calls += 1
        return self.payload


SEED = Paper(id="10/seed", title="Seed", abstract="seed abstract",
             external_ids=ExternalIds(doi="10/seed"))
PAPERS = [
    Paper(id="10/a", title="Paper A", external_ids=ExternalIds(doi="10/a")),
    Paper(id="10/b", title="Paper B", external_ids=ExternalIds(doi="10/b")),
]


async def test_answer_question_grounds_and_resolves_citations():
    fake = FakeCodex({
        "answer": "Both A and B use attention.",
        "citations": ["10/a", "10/b — Paper B", "10/ghost"],  # mixed forms + unknown
        "confidence": 1.4,  # should clamp
    })
    res = await answer_question(fake, "What do they use?", SEED, PAPERS, {}, "en")
    assert res.answer.startswith("Both A and B")
    assert res.citations == ["10/a", "10/b"]   # resolved + unknown dropped
    assert res.confidence == 1.0               # clamped


async def test_generate_web_context_uses_real_urls(monkeypatch):
    results = [
        SearchResult(title="Survey of X", url="https://ex.com/survey", snippet="a survey"),
        SearchResult(title="Recent X", url="https://ex.com/recent", snippet="recent work"),
    ]

    async def fake_search_many(queries, max_results=5):
        return results

    monkeypatch.setattr(report_mod, "search_many", fake_search_many)
    fake = FakeCodex({
        "overview": "External context overview.",
        "sources": [
            {"title": "Survey", "url": "https://ex.com/survey", "note": "good survey"},
            {"title": "Hallucinated", "url": "https://evil.com/fake", "note": "nope"},
        ],
    })
    report = await generate_web_context(fake, SEED, ["gap one"], language="en")
    assert report.level == "web"
    assert report.overview == "External context overview."
    urls = [s.url for s in report.sources]
    assert "https://ex.com/survey" in urls
    assert "https://evil.com/fake" not in urls   # not in search results -> dropped


async def test_generate_web_context_no_results(monkeypatch):
    async def empty(queries, max_results=5):
        return []

    monkeypatch.setattr(report_mod, "search_many", empty)
    report = await generate_web_context(FakeCodex({}), SEED, [], language="en")
    assert report.level == "web"
    assert report.sources == []
