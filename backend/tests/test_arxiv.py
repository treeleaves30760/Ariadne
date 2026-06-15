"""Tests for the arXiv Atom adapter."""

from __future__ import annotations

import httpx
import respx

from app.config import Settings
from app.models import ExternalIds
from app.sources.arxiv import Arxiv, _arxiv_id_from_url, _text
from app.storage.db import Database

ARXIV = "https://export.arxiv.org/api"

FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2601.14724v4</id>
    <title>HERMES: KV Cache as Hierarchical Memory</title>
    <summary>We propose HERMES.</summary>
    <published>2026-01-21T07:26:15Z</published>
    <link href="https://arxiv.org/abs/2601.14724v4" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/2601.14724v4" rel="related" type="application/pdf" title="pdf"/>
    <arxiv:primary_category term="cs.CV"/>
    <author><name>Haowei Zhang</name></author>
    <author><name>Xipeng Qiu</name></author>
  </entry>
</feed>"""

EMPTY = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def _settings() -> Settings:
    return Settings(arxiv_min_interval_s=0, http_max_retries=1)


async def _ax():
    db = await Database.connect(":memory:")
    client = httpx.AsyncClient()
    return db, client, Arxiv.build(client, _settings(), db)


def test_text_and_url_helpers():
    assert _text(None) is None
    assert _arxiv_id_from_url(None) is None
    assert _arxiv_id_from_url("http://arxiv.org/abs/2601.14724v4") == "2601.14724"
    assert _arxiv_id_from_url("http://example.com/x") is None


def test_parse_handles_bad_and_empty_xml():
    ax = Arxiv(None, _settings())  # fetcher unused by _parse
    assert ax._parse(None) == []
    assert ax._parse("<not valid xml") == []
    assert ax._parse(EMPTY) == []


def test_entry_to_paper_variants():
    ax = Arxiv(None, _settings())
    # synthesized DataCite DOI + arXiv id + pdf + category + year
    p = ax._parse(FEED)[0]
    assert p.external_ids.arxiv == "2601.14724"
    assert p.external_ids.doi == "10.48550/arxiv.2601.14724"
    assert p.year == 2026 and "/pdf/" in p.pdf_url
    assert p.fields_of_study == ["cs.CV"] and [a.name for a in p.authors][0] == "Haowei Zhang"
    # a publisher DOI is preferred over the synthesized DataCite one
    feed_doi = FEED.replace('<arxiv:primary_category term="cs.CV"/>',
                            "<arxiv:doi>10.1/real</arxiv:doi>")
    assert ax._parse(feed_doi)[0].external_ids.doi == "10.1/real"
    # entry without an id is dropped
    noid = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>X</title></entry></feed>'
    assert ax._parse(noid) == []
    # old-style id -> no synthesized DataCite DOI; canonical id falls back to arXiv
    old = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
           "<id>http://arxiv.org/abs/hep-th/9901001</id><title>Old</title></entry></feed>")
    op = ax._parse(old)[0]
    assert op.external_ids.doi is None and op.external_ids.arxiv == "hep-th/9901001"
    assert op.id == "arxiv:hep-th/9901001"


@respx.mock
async def test_arxiv_search():
    db, client, ax = await _ax()
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=FEED))
    try:
        cands = await ax.search("HERMES: KV Cache")
        assert cands[0].source == "arxiv"
        assert cands[0].external_ids.arxiv == "2601.14724"
        assert cands[0].external_ids.doi == "10.48550/arxiv.2601.14724"
        assert cands[0].year == 2026
        assert await ax.search("!!!") == []  # punctuation-only query -> no request
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_arxiv_get_paper_branches():
    db, client, ax = await _ax()
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=FEED))
    try:
        assert (await ax.get_paper("arxiv:2601.14724")).external_ids.arxiv == "2601.14724"
        assert (await ax.get_paper("x", ExternalIds(arxiv="2601.14724"))).year == 2026
        assert (await ax.get_paper("10.48550/arxiv.2601.14724")).external_ids.arxiv == "2601.14724"
        # unresolvable canonical / ext -> no fetch, None
        assert await ax.get_paper("s2:abc") is None
        assert await ax.get_paper("10.1/journal") is None
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_arxiv_get_paper_empty_feed():
    db, client, ax = await _ax()
    respx.get(f"{ARXIV}/query").mock(return_value=httpx.Response(200, text=EMPTY))
    try:
        assert await ax.get_paper("arxiv:2601.99999") is None
    finally:
        await client.aclose()
        await db.close()
