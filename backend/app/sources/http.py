"""Throttled, retrying, cached HTTP helper shared by source adapters."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.storage.db import Database


class Throttle:
    """Serialize calls per source so we honor a minimum interval between requests."""

    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.min_interval_s:
                await asyncio.sleep(self.min_interval_s - delta)
            self._last = time.monotonic()


class HttpFetcher:
    """GET JSON with throttling, retry/backoff on 429/5xx, and DB-backed caching."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        throttle: Throttle,
        *,
        db: Database | None = None,
        max_retries: int = 4,
        source: str = "http",
    ):
        self.client = client
        self.throttle = throttle
        self.db = db
        self.max_retries = max_retries
        self.source = source

    @staticmethod
    def _cache_key(method: str, url: str, params: dict | None, body: Any) -> str:
        import hashlib
        import json

        blob = json.dumps(
            {"m": method, "u": url, "p": params or {}, "b": body}, sort_keys=True, default=str
        )
        return f"{hashlib.sha256(blob.encode()).hexdigest()}"

    async def get_json(
        self,
        url: str,
        params: dict | None = None,
        *,
        headers: dict | None = None,
        use_cache: bool = True,
        ok_404: bool = False,
        max_retries: int | None = None,
    ) -> Any | None:
        return await self._request("GET", url, params=params, headers=headers,
                                   use_cache=use_cache, ok_404=ok_404, max_retries=max_retries)

    async def get_text(
        self,
        url: str,
        params: dict | None = None,
        *,
        headers: dict | None = None,
        use_cache: bool = True,
        ok_404: bool = False,
        max_retries: int | None = None,
    ) -> str | None:
        """Like :meth:`get_json` but returns the raw response body (e.g. arXiv Atom XML)."""
        return await self._request("GET", url, params=params, headers=headers,
                                   use_cache=use_cache, ok_404=ok_404,
                                   max_retries=max_retries, parse="text")

    async def post_json(
        self,
        url: str,
        json_body: Any,
        params: dict | None = None,
        *,
        headers: dict | None = None,
        use_cache: bool = True,
        max_retries: int | None = None,
    ) -> Any | None:
        return await self._request("POST", url, params=params, headers=headers,
                                   json_body=json_body, use_cache=use_cache,
                                   max_retries=max_retries)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        json_body: Any = None,
        use_cache: bool = True,
        ok_404: bool = False,
        max_retries: int | None = None,
        parse: str = "json",
    ) -> Any | None:
        retries = max_retries if max_retries is not None else self.max_retries
        key = self._cache_key(method, url, params, json_body)
        if use_cache and self.db is not None:
            cached = await self.db.cache_get(key)
            if cached is not None:
                return cached

        last_exc: Exception | None = None
        for attempt in range(retries):
            await self.throttle.wait()
            try:
                resp = await self.client.request(
                    method, url, params=params, headers=headers, json=json_body
                )
            except httpx.HTTPError as exc:  # network error -> backoff & retry
                last_exc = exc
                if attempt < retries - 1:
                    await asyncio.sleep(min(2**attempt, 20))
                continue

            if resp.status_code == 404 and ok_404:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2**attempt, 20)
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
                if attempt < retries - 1:  # don't sleep after the final attempt
                    await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            data = resp.text if parse == "text" else resp.json()
            if use_cache and self.db is not None:
                await self.db.cache_set(key, data)
            return data

        if ok_404:
            return None
        raise RuntimeError(f"{self.source}: request failed after {retries} retries: {last_exc}")
