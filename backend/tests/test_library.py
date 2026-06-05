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
