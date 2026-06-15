"""Unit tests for source conversion, id normalization, and merge logic."""

from __future__ import annotations

from app.models import Candidate, ExternalIds, Paper
from app.sources.ids import (
    arxiv_from_doi,
    canonical_id,
    detect_identifier,
    norm_arxiv,
    norm_doi,
    normalize_title,
)
from app.sources.merge import collapse_by_title, dedup_candidates, dedup_papers, merge_papers
from app.sources.openalex import OpenAlex, reconstruct_abstract
from app.sources.semantic_scholar import SemanticScholar, _paper_to_candidate


def test_norm_doi():
    assert norm_doi("https://doi.org/10.1/AbC") == "10.1/abc"
    assert norm_doi("doi:10.2/x") == "10.2/x"
    assert norm_doi(None) is None


def test_norm_arxiv():
    assert norm_arxiv("arXiv:1706.03762") == "1706.03762"
    assert norm_arxiv("1706.03762") == "1706.03762"
    assert norm_arxiv("https://arxiv.org/abs/2601.14724v4") == "2601.14724"  # URL + version
    assert norm_arxiv("https://arxiv.org/pdf/2601.14724") == "2601.14724"
    assert norm_arxiv("2601.14724v2") == "2601.14724"


def test_arxiv_from_doi():
    assert arxiv_from_doi("10.48550/arxiv.2601.14724") == "2601.14724"
    assert arxiv_from_doi("10.48550/arXiv.1706.03762v3") == "1706.03762"
    assert arxiv_from_doi("10.1145/other") is None
    assert arxiv_from_doi(None) is None


def test_detect_identifier():
    assert detect_identifier("https://arxiv.org/abs/2601.14724") == ("arxiv", "2601.14724")
    assert detect_identifier("arXiv:2601.14724v4") == ("arxiv", "2601.14724")
    assert detect_identifier("2601.14724") == ("arxiv", "2601.14724")
    assert detect_identifier("10.48550/arXiv.2601.14724") == ("arxiv", "2601.14724")
    assert detect_identifier("10.1145/3292500.3330701") == ("doi", "10.1145/3292500.3330701")
    assert detect_identifier("Attention Is All You Need") is None
    assert detect_identifier("   ") is None


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


def test_oa_to_paper_extracts_arxiv():
    # arXiv id recovered from the DataCite DOI
    p = OpenAlex._to_paper({
        "display_name": "X", "doi": "https://doi.org/10.48550/arxiv.2601.14724",
        "ids": {"openalex": "https://openalex.org/W1"},
    })
    assert p.external_ids.arxiv == "2601.14724"
    # arXiv id recovered from ids.arxiv (URL form)
    p2 = OpenAlex._to_paper({
        "display_name": "Y",
        "ids": {"openalex": "https://openalex.org/W2", "arxiv": "https://arxiv.org/abs/1706.03762"},
    })
    assert p2.external_ids.arxiv == "1706.03762"


def test_collapse_by_title_folds_doi_and_title_only():
    # The same paper indexed twice — once with a DOI, once title-only — collapses to one.
    a = Candidate(id="oa:W1", title="HERMES: KV Cache", source="openalex", citation_count=0,
                  external_ids=ExternalIds(openalex="W1"))
    b = Candidate(id="10.48550/arxiv.2601.14724", title="HERMES: KV Cache", source="openalex",
                  citation_count=0,
                  external_ids=ExternalIds(doi="10.48550/arxiv.2601.14724", arxiv="2601.14724",
                                           openalex="W2"))
    out = collapse_by_title([a, b])
    assert len(out) == 1
    assert out[0].external_ids.doi == "10.48550/arxiv.2601.14724"
    assert out[0].external_ids.arxiv == "2601.14724"
    # id recomputed from merged ids (DOI wins) so the survivor stays addressable
    assert out[0].id == "10.48550/arxiv.2601.14724"
    # distinct titles are preserved
    c = Candidate(id="oa:W3", title="Other", source="openalex",
                  external_ids=ExternalIds(openalex="W3"))
    assert len(collapse_by_title([a, c])) == 2
