"""Tests for OpenAlex / Semantic Scholar API methods (mocked HTTP via respx)."""

from __future__ import annotations

import httpx
import respx

from app.config import Settings
from app.models import ExternalIds
from app.sources.openalex import OpenAlex, reconstruct_abstract
from app.sources.semantic_scholar import SemanticScholar
from app.storage.db import Database

S2 = "https://api.semanticscholar.org/graph/v1"
OA = "https://api.openalex.org"


def _settings() -> Settings:
    return Settings(openalex_email="t@e.com", semantic_scholar_api_key="k",
                    s2_min_interval_s=0, openalex_min_interval_s=0, http_max_retries=1)


async def _oa():
    db = await Database.connect(":memory:")
    client = httpx.AsyncClient()
    return db, client, OpenAlex.build(client, _settings(), db)


async def _s2():
    db = await Database.connect(":memory:")
    client = httpx.AsyncClient()
    return db, client, SemanticScholar.build(client, _settings(), db)


# ------------------------------- OpenAlex -------------------------------- #
def test_reconstruct_abstract_empty_positions():
    assert reconstruct_abstract({"word": []}) is None  # non-empty dict, no positions


def test_oa_to_paper_edge_cases():
    assert OpenAlex._to_paper({}) is None                      # no title
    assert OpenAlex._to_paper({"display_name": "X"}) is None   # no usable id
    # title fallback + id taken from raw["id"]
    p = OpenAlex._to_paper({"title": "T", "id": "https://openalex.org/W3"})
    assert p.title == "T" and p.external_ids.openalex == "W3"
    # pdf from best_oa_location
    p2 = OpenAlex._to_paper({"display_name": "X", "ids": {"openalex": "https://openalex.org/W1"},
                             "best_oa_location": {"pdf_url": "http://x/p.pdf"}})
    assert p2.pdf_url == "http://x/p.pdf"
    # pdf from open_access fallback when best_oa_location has nothing
    p3 = OpenAlex._to_paper({"display_name": "Y", "ids": {"openalex": "https://openalex.org/W2"},
                             "best_oa_location": {}, "open_access": {"oa_url": "http://y/oa.pdf"}})
    assert p3.pdf_url == "http://y/oa.pdf"


def test_oa_path_branches():
    assert OpenAlex._oa_path("x", ExternalIds(openalex="W5")) == "W5"
    assert OpenAlex._oa_path("oa:W6") == "W6"
    assert OpenAlex._oa_path("s2:abc") == ""
    assert OpenAlex._oa_path("arxiv:1234") == ""
    assert OpenAlex._oa_path("10/doi") == "doi:10/doi"


@respx.mock
async def test_oa_get_paper_and_unaddressable():
    db, client, oa = await _oa()
    respx.get(f"{OA}/works/W9").mock(return_value=httpx.Response(200, json={
        "id": "https://openalex.org/W9", "display_name": "X",
        "ids": {"openalex": "https://openalex.org/W9"}}))
    try:
        p = await oa.get_paper("oa:W9")
        assert p.title == "X"
        assert await oa.get_paper("s2:abc") is None  # path empty -> None
        assert await oa.get_references("s2:abc", 10) == []  # _raw_work returns None
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_oa_citations_breaks_on_empty_page():
    db, client, oa = await _oa()
    respx.get(f"{OA}/works/W1").mock(return_value=httpx.Response(200, json={
        "id": "https://openalex.org/W1", "display_name": "Seed",
        "ids": {"openalex": "https://openalex.org/W1"}}))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json={"results": []}))
    try:
        assert await oa.get_citations("oa:W1", limit=200) == []  # first page empty -> break
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_oa_search():
    db, client, oa = await _oa()
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json={"results": [
        {"id": "https://openalex.org/W1", "display_name": "A",
         "ids": {"openalex": "https://openalex.org/W1"}, "cited_by_count": 5}]}))
    try:
        cands = await oa.search("a", limit=10)
        assert cands[0].title == "A" and cands[0].source == "openalex"
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_oa_references_and_citations():
    db, client, oa = await _oa()
    raw_work = {"id": "https://openalex.org/W1", "display_name": "Seed",
                "referenced_works": ["https://openalex.org/W2", "https://openalex.org/W3"],
                "ids": {"openalex": "https://openalex.org/W1"}}
    works = {"results": [
        {"id": "https://openalex.org/W2", "display_name": "Ref A",
         "ids": {"openalex": "https://openalex.org/W2"}},
        {"id": "https://openalex.org/W3", "display_name": "Ref B",
         "ids": {"openalex": "https://openalex.org/W3"}},
    ]}
    respx.get(f"{OA}/works/W1").mock(return_value=httpx.Response(200, json=raw_work))
    respx.get(f"{OA}/works").mock(return_value=httpx.Response(200, json=works))
    try:
        refs = await oa.get_references("oa:W1", limit=200)
        assert {p.title for p in refs} == {"Ref A", "Ref B"}
        cites = await oa.get_citations("oa:W1", limit=60)
        assert all(p.id for p in cites)
        # citation seed with no resolvable id -> []
        respx.get(f"{OA}/works/W404").mock(return_value=httpx.Response(404))
        assert await oa.get_citations("oa:W404", limit=10) == []
    finally:
        await client.aclose()
        await db.close()


# --------------------------- Semantic Scholar ---------------------------- #
def test_s2_to_paper_edge_cases():
    assert SemanticScholar._to_paper({}) is None                # no title
    assert SemanticScholar._to_paper({"title": "X"}) is None     # no usable id


def test_s2_path_id_branches():
    assert SemanticScholar._path_id("x", ExternalIds(s2="abc")) == "abc"
    # arXiv id wins over an unaddressable canonical / DataCite DOI (S2 400s on the latter)
    assert SemanticScholar._path_id("oa:W1", ExternalIds(arxiv="2601.14724")) == "ARXIV:2601.14724"
    assert SemanticScholar._path_id("s2:abc") == "abc"
    assert SemanticScholar._path_id("arxiv:1706.03762") == "ARXIV:1706.03762"
    assert SemanticScholar._path_id("oa:W1") == ""
    assert SemanticScholar._path_id("oa:W1", ExternalIds(doi="10/x")) == "DOI:10/x"  # oa: + DOI
    assert SemanticScholar._path_id("10/doi") == "DOI:10/doi"


@respx.mock
async def test_s2_search():
    db, client, s2 = await _s2()
    respx.get(f"{S2}/paper/search").mock(return_value=httpx.Response(200, json={"data": [
        {"paperId": "abc", "title": "A", "externalIds": {}}]}))
    try:
        cands = await s2.search("a", limit=5)
        assert cands[0].title == "A" and cands[0].source == "s2"
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_s2_batch_lookup():
    db, client, s2 = await _s2()
    respx.post(f"{S2}/paper/batch").mock(return_value=httpx.Response(200, json=[
        {"paperId": "p1", "citationCount": 12}, None]))
    try:
        assert await s2.batch_lookup([]) == []                    # empty ids -> no request
        res = await s2.batch_lookup(["ARXIV:1", "ARXIV:2"])
        assert res[0]["citationCount"] == 12 and res[1] is None
    finally:
        await client.aclose()
        await db.close()


async def test_s2_search_skipped_without_key():
    # Keyless S2 search short-circuits to [] with no network call.
    db = await Database.connect(":memory:")
    client = httpx.AsyncClient()
    s2 = SemanticScholar.build(
        client, Settings(s2_min_interval_s=0, http_max_retries=1), db
    )
    try:
        assert s2._headers is None
        assert await s2.search("anything") == []
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_s2_get_paper_and_neighbors():
    db, client, s2 = await _s2()
    respx.get(f"{S2}/paper/abc").mock(return_value=httpx.Response(200, json={
        "paperId": "abc", "title": "Seed", "externalIds": {}}))
    respx.get(f"{S2}/paper/abc/references").mock(return_value=httpx.Response(200, json={
        "data": [{"citedPaper": {"paperId": "r1", "title": "Ref", "externalIds": {}}}]}))
    respx.get(f"{S2}/paper/abc/citations").mock(return_value=httpx.Response(200, json={
        "data": [{"citingPaper": {"paperId": "c1", "title": "Cite", "externalIds": {}}}]}))
    try:
        assert (await s2.get_paper("s2:abc")).title == "Seed"
        assert (await s2.get_references("s2:abc", 200))[0].title == "Ref"
        assert (await s2.get_citations("s2:abc", 200))[0].title == "Cite"
        # unaddressable canonical -> None / []
        assert await s2.get_paper("oa:W1") is None
        assert await s2.get_references("oa:W1", 10) == []
    finally:
        await client.aclose()
        await db.close()
