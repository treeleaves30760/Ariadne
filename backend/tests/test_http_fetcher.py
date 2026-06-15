"""Tests for the throttled/retrying/cached HttpFetcher and Throttle."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.sources.http import HttpFetcher, Throttle
from app.storage.db import Database

URL = "https://api.test/x"


async def _no_sleep(*_a, **_k):
    return None


async def _fetcher(db: Database | None = None, max_retries: int = 3):
    client = httpx.AsyncClient()
    return client, HttpFetcher(client, Throttle(0), db=db, max_retries=max_retries, source="t")


@respx.mock
async def test_cache_hit_skips_network():
    db = await Database.connect(":memory:")
    key = HttpFetcher._cache_key("GET", URL, None, None)
    await db.cache_set(key, {"cached": True})
    client, f = await _fetcher(db)
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"net": True}))
    try:
        assert await f.get_json(URL) == {"cached": True}
        assert not route.called
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_404_with_ok_404_returns_none():
    respx.get(URL).mock(return_value=httpx.Response(404))
    client, f = await _fetcher()
    try:
        assert await f.get_json(URL, ok_404=True) is None
    finally:
        await client.aclose()


@respx.mock
async def test_retry_on_429_with_retry_after_then_success(monkeypatch):
    monkeypatch.setattr("app.sources.http.asyncio.sleep", _no_sleep)
    respx.get(URL).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"ok": 1}),
    ])
    client, f = await _fetcher(max_retries=3)
    try:
        assert await f.get_json(URL, use_cache=False) == {"ok": 1}
    finally:
        await client.aclose()


@respx.mock
async def test_retry_on_5xx_without_retry_after_then_success(monkeypatch):
    monkeypatch.setattr("app.sources.http.asyncio.sleep", _no_sleep)
    respx.get(URL).mock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, json={"ok": 2}),
    ])
    client, f = await _fetcher(max_retries=3)
    try:
        assert await f.get_json(URL, use_cache=False) == {"ok": 2}
    finally:
        await client.aclose()


@respx.mock
async def test_network_error_then_success(monkeypatch):
    monkeypatch.setattr("app.sources.http.asyncio.sleep", _no_sleep)
    respx.get(URL).mock(side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={"ok": 3})])
    client, f = await _fetcher(max_retries=3)
    try:
        assert await f.get_json(URL, use_cache=False) == {"ok": 3}
    finally:
        await client.aclose()


@respx.mock
async def test_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("app.sources.http.asyncio.sleep", _no_sleep)
    respx.get(URL).mock(return_value=httpx.Response(500))
    client, f = await _fetcher(max_retries=2)
    try:
        with pytest.raises(RuntimeError, match="request failed"):
            await f.get_json(URL, use_cache=False)
    finally:
        await client.aclose()


@respx.mock
async def test_ok_404_returns_none_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("app.sources.http.asyncio.sleep", _no_sleep)
    respx.get(URL).mock(return_value=httpx.Response(500))
    client, f = await _fetcher(max_retries=2)
    try:
        assert await f.get_json(URL, use_cache=False, ok_404=True) is None
    finally:
        await client.aclose()


@respx.mock
async def test_post_json_caches():
    db = await Database.connect(":memory:")
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"posted": True}))
    client, f = await _fetcher(db)
    try:
        assert await f.post_json(URL, {"q": 1}) == {"posted": True}
        assert await f.post_json(URL, {"q": 1}) == {"posted": True}  # served from cache
        assert route.call_count == 1
    finally:
        await client.aclose()
        await db.close()


@respx.mock
async def test_get_text_returns_raw_body():
    respx.get(URL).mock(return_value=httpx.Response(200, text="<feed/>"))
    client, f = await _fetcher()
    try:
        assert await f.get_text(URL, use_cache=False) == "<feed/>"
    finally:
        await client.aclose()


@respx.mock
async def test_max_retries_override_fails_fast(monkeypatch):
    monkeypatch.setattr("app.sources.http.asyncio.sleep", _no_sleep)
    route = respx.get(URL).mock(return_value=httpx.Response(429))
    client, f = await _fetcher(max_retries=5)
    try:
        # override to a single attempt -> one call, no trailing sleep, ok_404 -> None
        assert await f.get_json(URL, use_cache=False, ok_404=True, max_retries=1) is None
        assert route.call_count == 1
    finally:
        await client.aclose()


@respx.mock
async def test_network_error_exhausts_retries(monkeypatch):
    monkeypatch.setattr("app.sources.http.asyncio.sleep", _no_sleep)
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    client, f = await _fetcher(max_retries=2)
    try:
        with pytest.raises(RuntimeError, match="request failed"):
            await f.get_json(URL, use_cache=False)
    finally:
        await client.aclose()


async def test_throttle_waits_between_calls(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr("app.sources.http.asyncio.sleep", fake_sleep)
    t = Throttle(min_interval_s=10.0)
    await t.wait()  # first call: no wait needed
    await t.wait()  # second call immediately after: must sleep
    assert slept and slept[-1] > 0
