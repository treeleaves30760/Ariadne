"""Unit tests for source conversion, id normalization, and merge logic."""

from __future__ import annotations

from app.models import Author, ExternalIds, Paper
from app.sources.ids import canonical_id, norm_arxiv, norm_doi, normalize_title
from app.sources.merge import dedup_candidates, dedup_papers, merge_papers
from app.sources.openalex import OpenAlex, reconstruct_abstract
from app.sources.semantic_scholar import SemanticScholar, _paper_to_candidate


def test_norm_doi():
    assert norm_doi("https://doi.org/10.1/AbC") == "10.1/abc"
    assert norm_doi("doi:10.2/x") == "10.2/x"
    assert norm_doi(None) is None


def test_norm_arxiv():
    assert norm_arxiv("arXiv:1706.03762") == "1706.03762"
    assert norm_arxiv("1706.03762") == "1706.03762"


def test_canonical_id_prefers_doi():
    assert canonical_id(ExternalIds(doi="10.1/x", s2="abc")) == "10.1/x"
    assert canonical_id(ExternalIds(s2="abc")) == "s2:abc"
    assert canonical_id(ExternalIds(openalex="W123")) == "oa:W123"


def test_normalize_title():
    assert normalize_title("Attention Is All You Need!") == "attention is all you need"


def test_reconstruct_abstract():
    inv = {"Hello": [0], "world": [1], "again": [2]}
    assert reconstruct_abstract(inv) == "Hello world again"
    assert reconstruct_abstract(None) is None


def test_s2_to_paper():
    raw = {
        "paperId": "abc",
        "title": "Attention Is All You Need",
        "abstract": "We propose the Transformer.",
        "year": 2017,
        "venue": "NeurIPS",
        "citationCount": 100000,
        "fieldsOfStudy": ["Computer Science"],
        "externalIds": {"DOI": "10.5/transformer", "ArXiv": "1706.03762"},
        "authors": [{"name": "Ashish Vaswani", "authorId": "1"}],
        "tldr": {"model": "x", "text": "transformer summary"},
        "url": "https://example/abc",
    }
    p = SemanticScholar._to_paper(raw)
    assert p is not None
    assert p.id == "10.5/transformer"
    assert p.tldr == "transformer summary"
    assert p.external_ids.arxiv == "1706.03762"
    assert p.external_ids.s2 == "abc"
    assert _paper_to_candidate(p).source == "s2"


def test_oa_to_paper():
    raw = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.5/transformer",
        "display_name": "Attention Is All You Need",
        "publication_year": 2017,
        "cited_by_count": 99999,
        "ids": {"openalex": "https://openalex.org/W123"},
        "authorships": [
            {"author": {"display_name": "Ashish Vaswani", "id": "https://openalex.org/A1"}}
        ],
        "primary_location": {"source": {"display_name": "NeurIPS"}},
        "abstract_inverted_index": {"We": [0], "propose": [1]},
        "concepts": [{"display_name": "Deep learning"}],
    }
    p = OpenAlex._to_paper(raw)
    assert p is not None
    assert p.id == "10.5/transformer"  # DOI wins
    assert p.external_ids.openalex == "W123"
    assert p.abstract == "We propose"
    assert p.venue == "NeurIPS"


def test_merge_papers_prefers_s2_abstract_and_unions_ids():
    s2 = Paper(
        id="s2:abc", title="T", abstract="s2 abstract", tldr="tldr",
        external_ids=ExternalIds(s2="abc", arxiv="1706.03762"), sources=["s2"],
        citation_count=10,
    )
    oa = Paper(
        id="oa:W1", title="T", abstract="oa abstract", venue="NeurIPS",
        external_ids=ExternalIds(openalex="W1", doi="10.5/x"), sources=["openalex"],
        citation_count=12,
    )
    merged = merge_papers([oa, s2])  # order shouldn't matter
    assert merged.id == "10.5/x"          # DOI from OA wins canonical
    assert merged.abstract == "s2 abstract"  # S2 preferred
    assert merged.venue == "NeurIPS"      # filled from OA
    assert merged.tldr == "tldr"
    assert set(merged.sources) == {"s2", "openalex"}
    assert merged.citation_count == 12    # max


def test_dedup_papers_merges_by_doi():
    a = Paper(id="s2:abc", title="X", external_ids=ExternalIds(s2="abc", doi="10/x"), sources=["s2"])
    b = Paper(id="oa:W1", title="X", external_ids=ExternalIds(openalex="W1", doi="10/x"),
              sources=["openalex"])
    c = Paper(id="s2:zzz", title="Other", external_ids=ExternalIds(s2="zzz", doi="10/y"),
              sources=["s2"])
    out = dedup_papers([a, b, c])
    assert len(out) == 2
    merged = next(p for p in out if p.external_ids.doi == "10/x")
    assert set(merged.sources) == {"s2", "openalex"}


def test_dedup_candidates_dedups_by_title_without_doi():
    from app.models import Candidate

    a = Candidate(id="s2:abc", title="Same Title", source="s2", citation_count=5,
                  external_ids=ExternalIds(s2="abc"))
    b = Candidate(id="oa:W1", title="same title", source="openalex", citation_count=9,
                  external_ids=ExternalIds(openalex="W1"))
    out = dedup_candidates([a], [b])
    assert len(out) == 1
    assert out[0].external_ids.s2 == "abc"
    assert out[0].external_ids.openalex == "W1"
