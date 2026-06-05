"""Tests for the BFS graph expander using a synthetic citation graph."""

from __future__ import annotations

import re

from app.config import Settings
from app.graph.expander import GraphExpander
from app.models import ExternalIds, JobParams, Paper


def P(pid, title=None, cites=0):
    # DOI-based ids stay stable through the merge layer (canonical_id == the doi).
    return Paper(id=pid, title=title or pid, citation_count=cites,
                 external_ids=ExternalIds(doi=pid))


SEED = P("seed", "Seed paper")
R1, R2, NOISE = P("r1", cites=100), P("r2", cites=10), P("noise", cites=1)
C1 = P("c1", cites=50)
R1a = P("r1a", cites=20)
R1b = P("r1b", cites=5)

GRAPH = {
    ("seed", "reference"): [R1, R2, NOISE],
    ("seed", "citation"): [C1],
    ("r1", "reference"): [R1a],
    ("r1a", "reference"): [R1b],
}

RELEVANCE = {"r1": 0.9, "r2": 0.5, "c1": 0.8, "noise": 0.1, "r1a": 0.7, "r1b": 0.6}


class FakeLibrary:
    def __init__(self):
        self.calls = []

    async def get_neighbors(self, canonical, direction, limit, ext=None):
        self.calls.append((canonical, direction))
        return list(GRAPH.get((canonical, direction), []))


class FakeCodex:
    def __init__(self, max_calls=200):
        self._calls = 0
        self._max = max_calls

    @property
    def calls(self):
        return self._calls

    def remaining(self):
        return max(0, self._max - self._calls)

    async def run_structured(self, prompt, schema, *, model=None):
        self._calls += 1
        ids = re.findall(r"id:\s*(\S+)", prompt)
        props = schema.get("properties", {})
        if "overview" in props:  # report
            return {
                "overview": "ov",
                "clusters": [{"theme": "T", "summary": "s", "paper_ids": ids}],
                "must_reads": ids[:1],
                "gaps": ["g"],
            }
        item_props = props.get("results", {}).get("items", {}).get("properties", {})
        if "relevance" in item_props:
            return {"results": [
                {"paper_id": i, "relevance": RELEVANCE.get(i, 0.5), "reason": "r"} for i in ids
            ]}
        if "summary" in item_props:
            return {"results": [{"paper_id": i, "summary": f"sum {i}"} for i in ids]}
        return {}


async def _run(db, *, depth=3, max_nodes=600, k=80):
    settings = Settings(max_nodes=max_nodes, per_level_k=k, relevance_threshold=0.25,
                        max_codex_calls=200, web_search_enabled=False)
    params = JobParams(seed_id="seed", depth=depth, per_level_k=k)
    exp = GraphExpander("job1", SEED, params, library=FakeLibrary(), codex=FakeCodex(),
                        db=db, settings=settings)
    await exp.run()
    return exp


async def test_expander_keeps_relevant_drops_noise(db):
    exp = await _run(db)
    rows = await db.job_papers("job1")
    ids = {r["paper_id"] for r in rows}
    assert "seed" in ids
    assert {"r1", "r2", "c1"} <= ids   # level 1 relevant kept
    assert "r1a" in ids and "r1b" in ids
    assert "noise" not in ids          # below threshold


async def test_expander_edges_have_correct_direction(db):
    await _run(db)
    edges = {(e.src, e.dst, e.direction) for e in await db.job_edges("job1")}
    assert ("seed", "r1", "reference") in edges   # seed references r1
    assert ("c1", "seed", "citation") in edges    # c1 cites seed
    assert ("r1", "r1a", "reference") in edges


async def test_expander_generates_progressive_and_final_reports(db):
    await _run(db, depth=3)
    levels = await db.list_reports("job1")
    assert "3" in levels       # progressive report at depth 3
    assert "final" in levels


async def test_expander_respects_node_ceiling(db):
    exp = await _run(db, max_nodes=3)
    rows = await db.job_papers("job1")
    assert len(rows) <= 3
    assert any("ceiling" in n for n in exp.notes)


async def test_expander_writes_summaries(db):
    await _run(db)
    s = await db.get_summary("job1", "r1")
    assert s is not None and s.text == "sum r1"
