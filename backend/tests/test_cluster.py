"""Tests for AI dimensional clustering (faceted categorization)."""

from __future__ import annotations

from app.ai.cluster import (
    PALETTE,
    _match_id,
    _slug,
    build_clustering,
    build_prompt,
    categorize_corpus,
)
from app.models import ExternalIds, Paper


def P(pid, title=None, year=None, cites=0):
    return Paper(id=pid, title=title or pid, year=year, citation_count=cites,
                 external_ids=ExternalIds(doi=pid))


SEED = P("seed", "Seed", 2017)
PAPERS = [P("a", "A", 2020), P("b", "B", 2021), P("c", "C")]  # c has no year


def test_slug():
    assert _slug("Benchmarks & Datasets!") == "benchmarks-datasets"
    assert _slug("***") == "dim"  # nothing left after stripping


def test_match_id_exact_loose_and_longest_wins():
    valid = {"10/a", "10/ab"}
    assert _match_id("10/a", valid) == "10/a"
    assert _match_id("see 10/ab here", valid) == "10/ab"   # longest substring wins
    assert _match_id("unrelated", valid) is None


def test_build_prompt_includes_ids_summary_and_limit():
    prompt = build_prompt(SEED, PAPERS, {"a": "summary of A"}, "en", 6)
    assert "id: a" in prompt and "id: b" in prompt and "id: c" in prompt
    assert "at most 6" in prompt
    assert "summary of A" in prompt          # uses the provided summary
    assert "(2020)" in prompt and "C\n" in prompt  # year shown when present, omitted otherwise


def test_build_clustering_full_assignment_resolves_and_colours():
    data = {
        "dimensions": [
            {"label": "Methods", "description": "core methods"},
            {"label": "Benchmarks & Datasets", "description": "evaluation"},
        ],
        "assignments": [
            {"paper_id": "a", "primary": "Methods", "tags": ["Benchmarks & Datasets", ""]},
            {"paper_id": "b", "primary": "Benchmarks & Datasets", "tags": ["Methods"]},
            {"paper_id": "c", "primary": "Method", "tags": ["Methods"]},  # loose match; self-tag dropped
        ],
    }
    cl = build_clustering(data, PAPERS, 8)
    assert {d.id for d in cl.dimensions} == {"methods", "benchmarks-datasets"}
    methods = next(d for d in cl.dimensions if d.id == "methods")
    assert methods.color == PALETTE[0]
    assert set(methods.paper_ids) == {"a", "c"}           # c resolved to methods via loose match
    fa = next(f for f in cl.facets if f.paper_id == "a")
    assert fa.primary == "methods" and fa.tags == ["benchmarks-datasets"]
    fc = next(f for f in cl.facets if f.paper_id == "c")
    assert fc.tags == []                                  # tag equal to primary is dropped


def test_build_clustering_missing_papers_fall_into_other():
    data = {"dimensions": [{"label": "Methods", "description": ""}],
            "assignments": [{"paper_id": "a", "primary": "Methods", "tags": []}]}
    cl = build_clustering(data, PAPERS, 8)
    other = next(d for d in cl.dimensions if d.id == "other")
    assert set(other.paper_ids) == {"b", "c"}


def test_build_clustering_drops_dupes_blanks_unknowns_and_empty_dims():
    data = {
        "dimensions": [
            {"label": "Methods", "description": ""},
            {"label": "Methods", "description": "dup label ignored"},
            {"label": "   ", "description": "blank ignored"},
            {"label": "Empty Dim", "description": "no members → dropped"},
        ],
        "assignments": [
            {"paper_id": "a", "primary": "Methods", "tags": ["Unknown Dim"]},  # unknown tag dropped
            {"paper_id": "ghost", "primary": "Methods", "tags": []},           # unknown paper dropped
            {"paper_id": "a", "primary": "Methods", "tags": []},               # duplicate paper dropped
            {"paper_id": "b", "primary": "Nonexistent", "tags": []},           # unknown primary → skipped
        ],
    }
    cl = build_clustering(data, PAPERS, 8)
    ids = {d.id for d in cl.dimensions}
    assert "methods" in ids and "empty-dim" not in ids
    fa = next(f for f in cl.facets if f.paper_id == "a")
    assert fa.tags == []
    other = next(d for d in cl.dimensions if d.id == "other")
    assert set(other.paper_ids) == {"b", "c"}  # b (unknown primary) + c (unassigned)


def test_build_clustering_slug_collision_disambiguated():
    data = {"dimensions": [{"label": "Methods", "description": ""},
                           {"label": "Methods!", "description": ""}],
            "assignments": [{"paper_id": "a", "primary": "Methods", "tags": []},
                            {"paper_id": "b", "primary": "Methods!", "tags": []}]}
    cl = build_clustering(data, PAPERS, 8)
    named = {d.id for d in cl.dimensions if d.id != "other"}
    assert named == {"methods", "methods-2"}


def test_build_clustering_respects_max_dimensions():
    data = {"dimensions": [{"label": f"D{i}", "description": ""} for i in range(10)],
            "assignments": [{"paper_id": "a", "primary": "D0", "tags": []}]}
    cl = build_clustering(data, PAPERS, 3)
    named = [d for d in cl.dimensions if d.id != "other"]
    assert len(named) <= 3


class FakeCodex:
    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    async def run_structured(self, prompt, schema, *, model=None):
        self.prompts.append(prompt)
        return self.payload


async def test_categorize_corpus_excludes_seed_and_calls_codex():
    payload = {"dimensions": [{"label": "Methods", "description": "m"}],
               "assignments": [{"paper_id": "a", "primary": "Methods", "tags": []}]}
    codex = FakeCodex(payload)
    cl = await categorize_corpus(codex, SEED, [SEED, *PAPERS], {}, "en", max_dimensions=5)
    assert codex.prompts                       # codex was invoked
    assert "Methods" in {d.label for d in cl.dimensions}
    assert all(f.paper_id != "seed" for f in cl.facets)  # seed never clustered


async def test_categorize_corpus_seed_only_skips_codex():
    codex = FakeCodex({})
    cl = await categorize_corpus(codex, SEED, [SEED], {}, "en")
    assert cl.dimensions == [] and cl.facets == []
    assert codex.prompts == []                 # nothing to cluster → no call


async def test_categorize_corpus_tolerates_none_payload():
    codex = FakeCodex(None)
    cl = await categorize_corpus(codex, SEED, [SEED, *PAPERS], {}, "en")
    other = next(d for d in cl.dimensions if d.id == "other")
    assert set(other.paper_ids) == {"a", "b", "c"}  # None → everything to Other
