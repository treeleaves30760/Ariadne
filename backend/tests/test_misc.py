"""Small targeted tests: seed_profile, merge guard, web-report fallback, DB migration."""

from __future__ import annotations

import aiosqlite
import pytest

import app.ai.report as report_mod
from app.ai.relevance import seed_profile
from app.ai.report import generate_web_context
from app.ai.websearch import SearchResult
from app.models import ExternalIds, Paper
from app.sources.merge import merge_papers
from app.storage.db import Database

SEED = Paper(id="10/seed", title="Seed", external_ids=ExternalIds(doi="10/seed"))


def test_seed_profile_includes_year_and_fields():
    s = Paper(id="x", title="T", year=2020, abstract="abs", fields_of_study=["ML", "NLP"])
    prof = seed_profile(s)
    assert "Year: 2020" in prof
    assert "Fields: ML, NLP" in prof
    assert "Abstract: abs" in prof


def test_merge_papers_empty_raises():
    with pytest.raises(ValueError, match="at least one"):
        merge_papers([])


def test_canonical_id_arxiv_and_raise():
    from app.sources.ids import canonical_id

    assert canonical_id(ExternalIds(arxiv="1706.03762")) == "arxiv:1706.03762"
    with pytest.raises(ValueError, match="no usable identifier"):
        canonical_id(ExternalIds())


def test_prefilter_uses_abstract_and_fields():
    from app.graph.prefilter import prefilter

    seed = Paper(id="s", title="deep learning", abstract="neural networks for vision",
                 fields_of_study=["Computer Science"], external_ids=ExternalIds(doi="s"))
    cands = [Paper(id=f"c{i}", title=f"neural paper {i}", citation_count=i,
                   external_ids=ExternalIds(doi=f"c{i}")) for i in range(5)]
    out = prefilter(seed, cands, cap=2)
    assert len(out) == 2


class _FakeCodex:
    def __init__(self, payload):
        self.payload = payload

    def remaining(self):
        return 100

    async def run_structured(self, prompt, schema, *, model=None):
        return self.payload


async def test_web_context_falls_back_to_raw_results(monkeypatch):
    results = [SearchResult(title="R1", url="https://r1", snippet="s1"),
               SearchResult(title="R2", url="https://r2", snippet="s2")]

    async def fake_many(queries, max_results=5):
        return results

    monkeypatch.setattr(report_mod, "search_many", fake_many)
    # model returns a source whose URL is not in the results -> dropped -> fallback to raw
    codex = _FakeCodex({"overview": "ov", "sources": [{"title": "x", "url": "https://nope", "note": "n"}]})
    report = await generate_web_context(codex, SEED, ["a gap"], max_results=5)
    assert report.level == "web"
    assert {s.url for s in report.sources} == {"https://r1", "https://r2"}


async def test_web_context_matches_url_ignoring_trailing_slash(monkeypatch):
    results = [SearchResult(title="R1", url="https://r1/", snippet="s1")]

    async def fake_many(queries, max_results=5):
        return results

    monkeypatch.setattr(report_mod, "search_many", fake_many)
    codex = _FakeCodex({"overview": "ov", "sources": [{"title": "x", "url": "https://r1", "note": "n"}]})
    report = await generate_web_context(codex, SEED, [], max_results=5)
    assert report.sources[0].url == "https://r1/"   # resolved despite slash mismatch


async def test_db_migration_adds_name_column(tmp_path):
    dbfile = str(tmp_path / "old.db")
    conn = await aiosqlite.connect(dbfile)
    await conn.execute(
        "CREATE TABLE jobs (id TEXT PRIMARY KEY, params TEXT NOT NULL, "
        "progress TEXT NOT NULL, created_at TEXT NOT NULL, error TEXT)"
    )  # pre-`name` schema
    await conn.commit()
    await conn.close()

    db = await Database.connect(dbfile)
    try:
        cur = await db._conn.execute("PRAGMA table_info(jobs)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert "name" in cols
    finally:
        await db.close()
