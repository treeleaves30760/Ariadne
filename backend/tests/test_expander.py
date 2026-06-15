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


# ----------------------- edge-case branch coverage ----------------------- #
async def _run_with(db, *, emit=None, web=False, depth=3, max_nodes=600,
                    max_candidates=200, codex=None):
    settings = Settings(max_nodes=max_nodes, per_level_k=80, relevance_threshold=0.25,
                        max_codex_calls=200, web_search_enabled=web,
                        max_candidates_per_level=max_candidates)
    params = JobParams(seed_id="seed", depth=depth, per_level_k=80)
    exp = GraphExpander("job1", SEED, params, library=FakeLibrary(),
                        codex=codex or FakeCodex(), db=db, settings=settings, emit=emit)
    await exp.run()
    return exp


async def test_expander_invokes_emit_callback(db):
    seen: list[str] = []

    async def emit(e):
        seen.append(e.get("type"))

    await _run_with(db, emit=emit)
    assert "progress" in seen and "report_ready" in seen


async def test_expander_generates_web_report(db, monkeypatch):
    import app.ai.report as report_mod
    from app.ai.websearch import SearchResult

    async def fake_many(queries, max_results=5):
        return [SearchResult(title="S", url="https://s", snippet="x")]

    monkeypatch.setattr(report_mod, "search_many", fake_many)
    await _run_with(db, web=True)
    assert "web" in await db.list_reports("job1")


class BudgetCodex(FakeCodex):
    """Succeeds `fail_after` times, then raises CodexBudgetExceeded."""

    def __init__(self, fail_after=0):
        super().__init__()
        self.fail_after = fail_after

    async def run_structured(self, prompt, schema, *, model=None):
        from app.ai.codex_client import CodexBudgetExceeded
        if self._calls >= self.fail_after:
            raise CodexBudgetExceeded("budget")
        return await super().run_structured(prompt, schema, model=model)


async def test_expander_handles_budget_exhaustion(db):
    # 1st call (relevance) ok; 2nd (summaries) raises; later scoring/report also raise.
    exp = await _run_with(db, codex=BudgetCodex(fail_after=1))
    assert any("budget" in n for n in exp.notes)


async def test_expander_prefilters_when_over_cap(db):
    exp = await _run_with(db, depth=1, max_candidates=1)
    assert any("prefiltered" in n for n in exp.notes)


async def test_expander_stops_when_no_new_candidates(db):
    # r1b is discovered at level 3; level 4's frontier yields nothing new.
    # This path only emits a note event (it isn't appended to exp.notes), so capture emits.
    notes: list[str] = []

    async def emit(e):
        if e.get("type") == "note":
            notes.append(e.get("message", ""))

    await _run_with(db, depth=5, emit=emit)
    assert any("no new candidates" in n for n in notes)


class _WebBudgetCodex(FakeCodex):
    """Succeeds for every call except the web-report one (schema with `sources`)."""

    async def run_structured(self, prompt, schema, *, model=None):
        from app.ai.codex_client import CodexBudgetExceeded
        if "sources" in schema.get("properties", {}):
            raise CodexBudgetExceeded("budget")
        return await FakeCodex.run_structured(self, prompt, schema, model=model)


async def test_expander_web_report_budget_exhausted(db, monkeypatch):
    import app.ai.report as report_mod
    from app.ai.websearch import SearchResult

    async def fake_many(queries, max_results=5):
        return [SearchResult(title="S", url="https://s", snippet="x")]

    monkeypatch.setattr(report_mod, "search_many", fake_many)
    exp = await _run_with(db, web=True, codex=_WebBudgetCodex())
    assert any("web report" in n for n in exp.notes)


class _OneLowNode:
    async def get_neighbors(self, canonical, direction, limit, ext=None):
        if canonical == "seed" and direction == "reference":
            return [P("lowrel", cites=1)]
        return []


class _AllLowCodex(FakeCodex):
    async def run_structured(self, prompt, schema, *, model=None):
        self._calls += 1
        props = schema.get("properties", {})
        if "overview" in props:
            return {"overview": "o", "clusters": [], "must_reads": [], "gaps": []}
        ids = re.findall(r"id:\s*(\S+)", prompt)
        item_props = props.get("results", {}).get("items", {}).get("properties", {})
        if "relevance" in item_props:
            return {"results": [{"paper_id": i, "relevance": 0.0, "reason": "x"} for i in ids]}
        return {"results": []}


async def test_expander_cross_link_finds_sibling_edges(db):
    # seed→A,B at L1; A (a frontier at L2) also cites sibling B. The per-level pass
    # skips A→B (B isn't newly kept at L2), so the cross-link pass(1) must recover it.
    A, B = P("a", cites=10), P("b", cites=5)
    g = {
        ("seed", "reference"): [A, B], ("seed", "citation"): [],
        ("a", "reference"): [B], ("a", "citation"): [],
        ("b", "reference"): [], ("b", "citation"): [],
    }

    class Lib:
        async def get_neighbors(self, canonical, direction, limit, ext=None):
            return list(g.get((canonical, direction), []))

    settings = Settings(max_nodes=600, per_level_k=80, relevance_threshold=0.25,
                        max_codex_calls=200, web_search_enabled=False)
    params = JobParams(seed_id="seed", depth=2, per_level_k=80)
    exp = GraphExpander("job1", SEED, params, library=Lib(), codex=FakeCodex(),
                        db=db, settings=settings)
    await exp.run()
    edges = {(e.src, e.dst) for e in await db.job_edges("job1")}
    assert ("seed", "a") in edges and ("seed", "b") in edges  # tree backbone
    assert ("a", "b") in edges                                # sibling edge recovered


async def test_expander_cross_link_fetches_leaf_refs_with_cap(db):
    # depth 1 → A,B are leaves whose references were never fetched during expansion.
    # The cross-link pass(2) fetches them; cross_link_max_nodes=1 caps it to one leaf.
    A, B = P("a", cites=10), P("b", cites=5)
    g = {
        ("seed", "reference"): [A, B], ("seed", "citation"): [],
        ("a", "reference"): [B], ("b", "reference"): [A],
    }

    class Lib:
        async def get_neighbors(self, canonical, direction, limit, ext=None):
            return list(g.get((canonical, direction), []))

    settings = Settings(max_nodes=600, per_level_k=80, relevance_threshold=0.25,
                        max_codex_calls=200, web_search_enabled=False, cross_link_max_nodes=1)
    params = JobParams(seed_id="seed", depth=1, per_level_k=80)
    exp = GraphExpander("job1", SEED, params, library=Lib(), codex=FakeCodex(),
                        db=db, settings=settings)
    await exp.run()
    edges = {(e.src, e.dst) for e in await db.job_edges("job1")}
    assert ("a", "b") in edges                       # A's references fetched → A→B linked
    assert ("b", "a") not in edges                   # B skipped by the cap
    assert any("capped" in n for n in exp.notes)


async def test_expander_breaks_when_nothing_kept(db):
    settings = Settings(max_nodes=600, per_level_k=80, relevance_threshold=0.25,
                        max_codex_calls=200, web_search_enabled=False)
    params = JobParams(seed_id="seed", depth=3, per_level_k=80)
    exp = GraphExpander("job1", SEED, params, library=_OneLowNode(), codex=_AllLowCodex(),
                        db=db, settings=settings)
    await exp.run()
    rows = await db.job_papers("job1")
    assert {r["paper_id"] for r in rows} == {"seed"}  # everything scored below threshold
