"""Tests for open-access PDF fetching/extraction (mocked HTTP + PdfReader)."""

from __future__ import annotations

import sys

import httpx
import respx

import app.sources.fulltext as ft
from app.sources.fulltext import _extract, fetch_pdf_text

PDF_URL = "https://x/p.pdf"


class _FakePage:
    def __init__(self, text):
        self._t = text

    def extract_text(self):
        return self._t


def test_extract_success_truncates_at_max_chars(monkeypatch):
    class Reader:
        def __init__(self, *_a, **_k):
            self.pages = [_FakePage("x" * 10000)]

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    out = _extract(b"data", max_chars=6000)
    assert out is not None and len(out) == 6000


def test_extract_blank_returns_none(monkeypatch):
    class Reader:
        def __init__(self, *_a, **_k):
            self.pages = [_FakePage("")]

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    assert _extract(b"data", 100) is None


def test_extract_reader_error_returns_none(monkeypatch):
    class Reader:
        def __init__(self, *_a, **_k):
            raise ValueError("corrupt")

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    assert _extract(b"data", 100) is None


def test_extract_import_error_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)  # makes `from pypdf import ...` raise
    assert _extract(b"data", 100) is None


async def test_fetch_empty_url():
    assert await fetch_pdf_text("") is None


@respx.mock
async def test_fetch_success(monkeypatch):
    monkeypatch.setattr(ft, "_extract", lambda data, mc: "extracted")
    respx.get(PDF_URL).mock(return_value=httpx.Response(
        200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}))
    assert await fetch_pdf_text(PDF_URL) == "extracted"


@respx.mock
async def test_fetch_non_200_returns_none():
    respx.get(PDF_URL).mock(return_value=httpx.Response(404))
    assert await fetch_pdf_text(PDF_URL) is None


@respx.mock
async def test_fetch_non_pdf_content_returns_none():
    respx.get("https://x/page").mock(return_value=httpx.Response(
        200, content=b"<html>", headers={"content-type": "text/html"}))
    assert await fetch_pdf_text("https://x/page") is None


@respx.mock
async def test_fetch_network_error_returns_none():
    respx.get(PDF_URL).mock(side_effect=httpx.ConnectError("down"))
    assert await fetch_pdf_text(PDF_URL) is None
