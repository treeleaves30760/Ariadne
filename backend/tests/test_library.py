"""Integration tests for PaperLibrary using mocked HTTP (respx)."""

from __future__ import annotations

import httpx
import respx

from app.config import Settings
from app.services.library import PaperLibrary

S2 = "https://api.semanticscholar.org/graph/v1"
OA = "https://api.openalex.org"


def _settings() -> Settings:
    return Settings(
        openalex_email="t@example.com",
        s2_min_interval_s=0,
        openalex_min_interval_s=0,
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
