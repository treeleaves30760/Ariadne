"""Tests for the DuckDuckGo web-search wrapper (mocked DDGS)."""

from __future__ import annotations

import sys

import app.ai.websearch as ws
from app.ai.websearch import SearchResult, _search_sync, search, search_many


class _FakeDDGS:
    results: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def text(self, query, max_results=5):
        return _FakeDDGS.results


def test_search_sync_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "ddgs", None)
    assert _search_sync("q", 5) == []


def test_search_sync_parses_results(monkeypatch):
    _FakeDDGS.results = [
        {"href": "https://a", "title": "A", "body": "abody"},
        {"url": "https://b", "title": "B", "snippet": "bbody"},
        {"href": "", "title": "no-url"},      # dropped (no url)
        {"href": "https://c", "title": ""},   # dropped (no title)
    ]
    monkeypatch.setattr("ddgs.DDGS", _FakeDDGS)
    out = _search_sync("q", 5)
    assert [r.url for r in out] == ["https://a", "https://b"]
    assert out[0].snippet == "abody"


def test_search_sync_handles_exception(monkeypatch):
    class Boom(_FakeDDGS):
        def text(self, *_a, **_k):
            raise RuntimeError("network")

    monkeypatch.setattr("ddgs.DDGS", Boom)
    assert _search_sync("q", 5) == []


async def test_search_runs_off_thread(monkeypatch):
    monkeypatch.setattr(ws, "_search_sync", lambda q, n: [SearchResult(title="T", url="https://t")])
    out = await search("q")
    assert out[0].url == "https://t"


async def test_search_many_dedupes_by_url(monkeypatch):
    async def fake_search(q, max_results=5):
        return [SearchResult(title="dup", url="https://dup"),
                SearchResult(title=q, url=f"https://{q}")]

    monkeypatch.setattr(ws, "search", fake_search)
    out = await search_many(["x", "y"])
    urls = [r.url for r in out]
    assert urls.count("https://dup") == 1
    assert "https://x" in urls and "https://y" in urls
