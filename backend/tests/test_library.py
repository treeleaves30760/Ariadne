"""Integration tests for PaperLibrary using mocked HTTP (respx)."""

from __future__ import annotations

import asyncio

import httpx
import respx

from app.config import Settings
from app.models import Candidate, ExternalIds
from app.services.library import PaperLibrary

S2 = "https://api.semanticscholar.org/graph/v1"
OA = "https://api.openalex.org"
ARXIV = "https://export.arxiv.org/api"

ATOM_EMPTY = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
ARXIV_FEED = (
    '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">'
    "<entry><id>http://arxiv.org/abs/2601.14724v1</id><title>HERMES Paper</title>"
    "<published>2026-01-21T00:00:00Z</published></entry></feed>"
)


def _settings() -> Settings:
    return Settings(
        openalex_email="t@example.com",
        semantic_scholar_api_key="k",  # exercise the S2 path (keyless search is skipped)
        s2_min_interval_s=0,
        openalex_min_interval_s=0,
        arxiv_min_interval_s=0,
        http_max_retries=1,
    )


S2_SEARCH = {
    "data": [
        {
            "paperId": "abc",
            "title": "Attention Is All You Need",
            "year": 2017,
            "citationCount": 100000,
            "externalIds": {"DOI": "10.5/transformer"},
            "authors": [{"name": "Vaswani"}],
        }
    ]
}
OA_SEARCH = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.5/transformer",
            "display_name": "Attention Is All You Need",
            "publication_year": 2017,
            "cited_by_count": 99000,
            "ids": {"openalex": "https://openalex.org/W1"},
            "authorships": [{"author": {"display_name": "Vaswani", "id": "https://openalex.org/A1"}}],
        },
        {
            "id": "https://openalex.org/W2",
            "doi": "https://doi.org/10.9/bert",
            "display_name": "BERT",
            "publication_year": 2018,
            "cited_by_count": 80000,
            "ids": {"openalex": "https://openalex.org/W2"},
            "authorships": [{"author": {"display_name": "Devlin", "id": "https://openalex.org/A2"}}],
        },
    ]
}


@respx.mock
async def test_resolve_merges_sources():
    respx.get(f"{S2}/paper/search").mock(return_value=httpx.Response(200, json=S2_SEARCH))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json=OA_SEARCH))
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=ATOM_EMPTY))
    respx.post(f"{S2}/paper/batch").mock(return_value=httpx.Response(200, json=[]))

    db_settings = _settings()
    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, db_settings)
    try:
        cands = await lib.resolve("attention is all you need", limit=10)
    finally:
        await lib.aclose()
        await db.close()

    # The transformer paper appears in both -> deduped to one with both ids.
    titles = [c.title for c in cands]
    assert "BERT" in titles
    transformer = next(c for c in cands if c.external_ids.doi == "10.5/transformer")
    assert transformer.external_ids.s2 == "abc"
    assert transformer.external_ids.openalex == "W1"
    # ranked by citation count -> transformer first
    assert cands[0].external_ids.doi == "10.5/transformer"


@respx.mock
async def test_resolve_survives_s2_failure():
    respx.get(f"{S2}/paper/search").mock(return_value=httpx.Response(429, json={"code": "429"}))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json=OA_SEARCH))
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=ATOM_EMPTY))
    respx.post(f"{S2}/paper/batch").mock(return_value=httpx.Response(200, json=[]))

    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        cands = await lib.resolve("x", limit=10)
    finally:
        await lib.aclose()
        await db.close()
    assert len(cands) == 2  # OpenAlex still returns results


@respx.mock
async def test_get_paper_merges_sources_and_caches():
    from app.storage.db import Database

    respx.get(f"{S2}/paper/DOI:10.5/t").mock(return_value=httpx.Response(200, json={
        "paperId": "abc", "title": "T", "externalIds": {"DOI": "10.5/t"}}))
    respx.get(f"{OA}/works/doi:10.5/t").mock(return_value=httpx.Response(200, json={
        "id": "https://openalex.org/W1", "display_name": "T",
        "doi": "https://doi.org/10.5/t", "ids": {"openalex": "https://openalex.org/W1"}}))
    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        p = await lib.get_paper("10.5/t")
        assert p is not None
        assert p.external_ids.s2 == "abc" and p.external_ids.openalex == "W1"
        assert await db.get_paper("10.5/t") is not None  # cached
    finally:
        await lib.aclose()
        await db.close()


@respx.mock
async def test_get_paper_none_when_both_miss():
    from app.storage.db import Database

    respx.get(f"{S2}/paper/DOI:10/none").mock(return_value=httpx.Response(404))
    respx.get(f"{OA}/works/doi:10/none").mock(return_value=httpx.Response(404))
    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        assert await lib.get_paper("10/none") is None
    finally:
        await lib.aclose()
        await db.close()


@respx.mock
async def test_get_neighbors_falls_back_to_openalex():
    from app.storage.db import Database

    # S2 has no path for an oa:-only id, so neighbors fall through to OpenAlex.
    respx.get(f"{OA}/works/W1").mock(return_value=httpx.Response(200, json={
        "id": "https://openalex.org/W1", "display_name": "Seed",
        "referenced_works": ["https://openalex.org/W2"],
        "ids": {"openalex": "https://openalex.org/W1"}}))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json={"results": [
        {"id": "https://openalex.org/W2", "display_name": "Ref",
         "ids": {"openalex": "https://openalex.org/W2"}}]}))
    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        papers = await lib.get_neighbors("oa:W1", "reference", 50)
        assert papers[0].title == "Ref"
        assert await db.get_paper(papers[0].id) is not None  # cached
    finally:
        await lib.aclose()
        await db.close()


async def test_safe_swallows_exceptions():
    from app.services.library import _safe

    async def boom():
        raise RuntimeError("x")

    async def ok():
        return 5

    assert await _safe(boom(), "default") == "default"
    assert await _safe(ok(), None) == 5


async def test_aclose_without_client_is_noop():
    from app.storage.db import Database
    from app.services.library import PaperLibrary

    db = await Database.connect(":memory:")
    client = httpx.AsyncClient()
    lib = PaperLibrary(client, db, _settings())  # constructed directly: no `_client` attr
    try:
        await lib.aclose()  # getattr(_client) is None -> no-op
    finally:
        await client.aclose()
        await db.close()


# --------------------------- identifier resolve --------------------------- #
@respx.mock
async def test_resolve_identifier_arxiv_id():
    # A bare arXiv id resolves straight to that paper via the arXiv source.
    respx.get(f"{S2}/paper/ARXIV:2601.14724").mock(return_value=httpx.Response(404))
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=ARXIV_FEED))
    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        cands = await lib.resolve("2601.14724", limit=12)
        assert len(cands) == 1
        assert cands[0].external_ids.arxiv == "2601.14724"
        assert "arxiv" in cands[0].source
    finally:
        await lib.aclose()
        await db.close()


@respx.mock
async def test_resolve_identifier_doi():
    doi = "10.1145/3292500.3330701"
    respx.get(f"{S2}/paper/DOI:{doi}").mock(return_value=httpx.Response(200, json={
        "paperId": "abc", "title": "Some Paper", "externalIds": {"DOI": doi}}))
    respx.get(f"{OA}/works/doi:{doi}").mock(return_value=httpx.Response(200, json={
        "id": "https://openalex.org/W1", "display_name": "Some Paper",
        "doi": f"https://doi.org/{doi}", "ids": {"openalex": "https://openalex.org/W1"}}))
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=ATOM_EMPTY))
    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        cands = await lib.resolve(doi, limit=12)
        assert len(cands) == 1
        assert cands[0].external_ids.s2 == "abc" and cands[0].external_ids.openalex == "W1"
    finally:
        await lib.aclose()
        await db.close()


@respx.mock
async def test_resolve_identifier_miss_falls_back_to_search():
    # The id lookup finds nothing -> resolve falls through to a keyword search.
    respx.get(f"{S2}/paper/ARXIV:2601.99999").mock(return_value=httpx.Response(404))
    respx.post(f"{S2}/paper/batch").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{S2}/paper/search").mock(return_value=httpx.Response(429, json={}))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json=OA_SEARCH))
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=ATOM_EMPTY))
    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        cands = await lib.resolve("2601.99999", limit=12)
        assert len(cands) == 2  # keyword fallback returned the OpenAlex results
    finally:
        await lib.aclose()
        await db.close()


# ----------------------- ranking + duplicate folding ---------------------- #
OA_HERMES = {"results": [
    {"id": "https://openalex.org/W_other",
     "doi": "https://doi.org/10.48550/arxiv.2410.04466",
     "display_name": "Large Language Model Inference Acceleration",
     "publication_year": 2024, "cited_by_count": 3,
     "ids": {"openalex": "https://openalex.org/W_other"}},
    {"id": "https://openalex.org/W459392",
     "display_name": "HERMES: KV Cache as Hierarchical Memory",
     "publication_year": 2026, "cited_by_count": 0,
     "ids": {"openalex": "https://openalex.org/W459392"}},
    {"id": "https://openalex.org/W405420",
     "doi": "https://doi.org/10.48550/arxiv.2601.14724",
     "display_name": "HERMES: KV Cache as Hierarchical Memory",
     "publication_year": 2026, "cited_by_count": 0,
     "ids": {"openalex": "https://openalex.org/W405420"}},
]}


@respx.mock
async def test_resolve_ranks_exact_match_and_collapses_duplicates():
    # Reproduces the HERMES bug: S2 is 429, OpenAlex returns the paper twice
    # (0 citations) alongside a higher-cited but irrelevant hit.
    respx.get(f"{S2}/paper/search").mock(return_value=httpx.Response(429, json={}))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json=OA_HERMES))
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=ATOM_EMPTY))
    respx.post(f"{S2}/paper/batch").mock(return_value=httpx.Response(200, json=[]))
    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        cands = await lib.resolve("HERMES: KV Cache as Hierarchical Memory", limit=12)
        hermes = [c for c in cands if c.title.startswith("HERMES")]
        assert len(hermes) == 1                  # two OpenAlex records folded into one
        assert cands[0] is hermes[0]             # exact match ranks first despite 0 citations
        assert hermes[0].external_ids.arxiv == "2601.14724"
        assert hermes[0].external_ids.doi == "10.48550/arxiv.2601.14724"
        # id is the DOI (not an unaddressable oa:…) so the seed routes to S2 for neighbors
        assert hermes[0].id == "10.48550/arxiv.2601.14724"
    finally:
        await lib.aclose()
        await db.close()


@respx.mock
async def test_resolve_enriches_citation_counts():
    # OpenAlex reports 0 cites for recent papers; S2's batch backfills real counts + s2 ids.
    respx.get(f"{S2}/paper/search").mock(return_value=httpx.Response(429, json={}))
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=ATOM_EMPTY))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json={"results": [
        {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.48550/arxiv.2601.14724",
         "display_name": "HERMES", "publication_year": 2026, "cited_by_count": 0,
         "ids": {"openalex": "https://openalex.org/W1"}},
        {"id": "https://openalex.org/W2", "doi": "https://doi.org/10.1145/other",
         "display_name": "Other", "publication_year": 2026, "cited_by_count": 0,
         "ids": {"openalex": "https://openalex.org/W2"}},
    ]}))
    # aligned with request order: HERMES (via arXiv id) gets a count; the 2nd id is unknown (null)
    respx.post(f"{S2}/paper/batch").mock(return_value=httpx.Response(200, json=[
        {"paperId": "s2hermes", "citationCount": 12}, None]))
    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, _settings())
    try:
        cands = await lib.resolve("HERMES", limit=10)
        hermes = next(c for c in cands if c.title == "HERMES")
        other = next(c for c in cands if c.title == "Other")
        assert hermes.citation_count == 12 and hermes.external_ids.s2 == "s2hermes"
        assert other.citation_count == 0 and other.external_ids.s2 is None  # null result left as-is
    finally:
        await lib.aclose()
        await db.close()


def test_relevance_scoring():
    from app.services.library import _relevance

    assert _relevance("", "x") == 0.0                                  # empty query
    assert _relevance("x", "") == 0.0                                  # empty title
    assert _relevance("a b c", "a b c") == 3.0                         # exact match
    assert _relevance("transformer", "the transformer model") == 2.0   # substring
    assert _relevance("a c", "a b") == 0.5                             # token overlap


async def test_resolve_bounds_slow_source(monkeypatch):
    # A source that exceeds the per-source budget is dropped; the fast one survives.
    settings = Settings(openalex_email="t@e.com", s2_min_interval_s=0, openalex_min_interval_s=0,
                        arxiv_min_interval_s=0, http_max_retries=1, search_timeout_s=0.05)
    from app.storage.db import Database

    db = await Database.connect(":memory:")
    lib = PaperLibrary.build(db, settings)

    async def slow(*_a, **_k):
        await asyncio.sleep(1)
        return []

    async def fast_oa(*_a, **_k):
        return [Candidate(id="oa:W1", title="Fast", source="openalex",
                          external_ids=ExternalIds(openalex="W1"))]

    monkeypatch.setattr(lib.s2, "search", slow)
    monkeypatch.setattr(lib.ax, "search", slow)
    monkeypatch.setattr(lib.oa, "search", fast_oa)
    try:
        cands = await lib.resolve("anything", limit=5)
        assert [c.title for c in cands] == ["Fast"]
    finally:
        await lib.aclose()
        await db.close()
