"""Tests for the Codex client plumbing and the relevance/summarize/report tasks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.codex_client import (
    CodexBudgetExceeded,
    CodexClient,
    _extract_json,
    _strip_fences,
)
from app.ai.relevance import score_relevance
from app.ai.report import generate_report
from app.ai.summarize import summarize_papers
from app.config import Settings
from app.models import ExternalIds, Paper


# --------------------------- parsing helpers ----------------------------- #
def test_strip_fences():
    assert _strip_fences("```json\n{\"a\":1}\n```") == '{"a":1}'
    assert _strip_fences('{"a":1}') == '{"a":1}'


def test_extract_json_with_noise():
    assert _extract_json("here you go: {\"a\": 1} done") == {"a": 1}
    assert _extract_json("```\n[1,2,3]\n```") == [1, 2, 3]


# ------------------------- codex client (faked) -------------------------- #
class _FakeProc:
    def __init__(self, out_path: Path, payload: dict, returncode: int = 0):
        self._out_path = out_path
        self._payload = payload
        self.returncode = returncode

    async def communicate(self, _input: bytes):
        self._out_path.write_text(json.dumps(self._payload), encoding="utf-8")
        return b"", b""


def _patch_exec(monkeypatch, payload: dict, returncode: int = 0):
    async def fake_exec(*args, **kwargs):
        out_path = Path(args[args.index("-o") + 1])
        return _FakeProc(out_path, payload, returncode)

    monkeypatch.setattr("app.ai.codex_client.asyncio.create_subprocess_exec", fake_exec)


async def test_run_structured_reads_output_file(monkeypatch):
    _patch_exec(monkeypatch, {"answer": "hello", "score": 0.5})
    codex = CodexClient(Settings())
    result = await codex.run_structured("hi", {"type": "object"})
    assert result == {"answer": "hello", "score": 0.5}
    assert codex.calls == 1


async def test_budget_enforced(monkeypatch):
    _patch_exec(monkeypatch, {"ok": True})
    codex = CodexClient(Settings(), max_calls=1)
    await codex.run_structured("a", {"type": "object"})
    assert codex.remaining() == 0
    with pytest.raises(CodexBudgetExceeded):
        await codex.run_structured("b", {"type": "object"})


# ----------------------------- fake codex -------------------------------- #
class FakeCodex:
    def __init__(self, payloads: list[dict]):
        self.payloads = payloads
        self.calls = 0

    async def run_structured(self, prompt, schema, *, model=None):
        p = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return p


def _paper(pid, title, year=2020):
    return Paper(id=pid, title=title, year=year, external_ids=ExternalIds(s2=pid.replace("s2:", "")))


SEED = Paper(id="10/seed", title="Seed", abstract="seed abstract",
             external_ids=ExternalIds(doi="10/seed"))


async def test_score_relevance_maps_by_id_and_clamps():
    cands = [_paper("s2:a", "A"), _paper("s2:b", "B")]
    fake = FakeCodex([{"results": [
        {"paper_id": "s2:a", "relevance": 1.5, "reason": "core"},
        {"paper_id": "s2:b", "relevance": -0.2, "reason": "weak"},
        {"paper_id": "s2:ghost", "relevance": 0.9, "reason": "ignored"},
    ]}])
    res = await score_relevance(fake, SEED, cands, batch_size=20)
    by = {r.paper_id: r for r in res}
    assert by["s2:a"].relevance == 1.0   # clamped
    assert by["s2:b"].relevance == 0.0   # clamped
    assert "s2:ghost" not in by          # unknown id dropped


async def test_score_relevance_batches():
    cands = [_paper(f"s2:{i}", f"P{i}") for i in range(45)]
    fake = FakeCodex([{"results": [{"paper_id": p.id, "relevance": 0.5, "reason": "x"}
                                   for p in cands]}])
    await score_relevance(fake, SEED, cands, batch_size=20)
    assert fake.calls == 3  # 20 + 20 + 5


async def test_summarize_papers():
    cands = [_paper("s2:a", "A")]
    fake = FakeCodex([{"results": [{"paper_id": "s2:a", "summary": "does X"}]}])
    out = await summarize_papers(fake, SEED, cands, language="en")
    assert out[0].text == "does X"
    assert out[0].language == "en"


async def test_generate_report():
    papers = [_paper("s2:a", "A"), _paper("s2:b", "B")]
    fake = FakeCodex([{
        "overview": "ov",
        "clusters": [{"theme": "T", "summary": "s", "paper_ids": ["s2:a", "s2:b"]}],
        "must_reads": ["s2:a"],
        "gaps": ["gap1"],
    }])
    report = await generate_report(fake, SEED, papers, {}, level="3", language="en")
    assert report.level == "3"
    assert report.overview == "ov"
    assert report.clusters[0].paper_ids == ["s2:a", "s2:b"]
    assert report.must_reads == ["s2:a"]
