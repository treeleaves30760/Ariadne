"""Fetch and extract text from open-access PDFs (a 'read the PDF' tool for QA)."""

from __future__ import annotations

import asyncio
import io

import httpx


def _extract(data: bytes, max_chars: int) -> str | None:
    try:
        from pypdf import PdfReader
    except Exception:
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            txt = page.extract_text() or ""
            parts.append(txt)
            total += len(txt)
            if total >= max_chars:
                break
        text = "\n".join(parts).strip()
        return text[:max_chars] if text else None
    except Exception:
        return None


async def fetch_pdf_text(url: str, *, max_chars: int = 6000, timeout: float = 25.0) -> str | None:
    """Download a PDF and return extracted text (truncated). Never raises."""
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "PaperConnector/1.0"})
            if resp.status_code != 200:
                return None
            ctype = resp.headers.get("content-type", "")
            if "pdf" not in ctype and not url.lower().endswith(".pdf"):
                return None
            data = resp.content
    except Exception:
        return None
    return await asyncio.to_thread(_extract, data, max_chars)
