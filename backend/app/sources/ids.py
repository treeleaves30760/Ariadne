"""Identifier normalization and canonical-id selection."""

from __future__ import annotations

import re

from app.models import ExternalIds


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:", "", d, flags=re.I)
    return d.lower() or None


def norm_openalex(oa: str | None) -> str | None:
    if not oa:
        return None
    return oa.rstrip("/").split("/")[-1].strip() or None


def norm_arxiv(ax: str | None) -> str | None:
    if not ax:
        return None
    s = ax.strip()
    s = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", s, flags=re.I)  # URL form
    s = re.sub(r"^arxiv:", "", s, flags=re.I)                            # "arXiv:" prefix
    s = re.sub(r"v\d+$", "", s)                                          # drop version suffix
    return s or None


def arxiv_from_doi(doi: str | None) -> str | None:
    """Recover an arXiv id from its standard DataCite DOI (10.48550/arXiv.<id>)."""
    if not doi:
        return None
    m = re.fullmatch(r"10\.48550/arxiv\.(.+)", doi.strip(), flags=re.I)
    return norm_arxiv(m.group(1)) if m else None


_ARXIV_NEW = r"\d{4}\.\d{4,5}"  # modern arXiv id, e.g. 2601.14724


def detect_identifier(query: str) -> tuple[str, str] | None:
    """Classify a resolve query that is itself an identifier.

    Returns ``("arxiv", id)`` for an arXiv id / URL, ``("doi", doi)`` for a DOI,
    or ``None`` for a free-text (title / keyword) query. An arXiv DataCite DOI is
    reported as an arXiv id so it routes to the authoritative source.
    """
    q = query.strip()
    if not q:
        return None
    low = q.lower()
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(" + _ARXIV_NEW + r")(?:v\d+)?", low)
    if m:
        return ("arxiv", m.group(1))
    m = re.fullmatch(r"(?:arxiv:\s*)?(" + _ARXIV_NEW + r")(?:v\d+)?", low)
    if m:
        return ("arxiv", m.group(1))
    m = re.search(r"(10\.\d{4,9}/\S+)", low)
    if m:
        doi = norm_doi(m.group(1))
        ax = arxiv_from_doi(doi)
        return ("arxiv", ax) if ax else ("doi", doi)
    return None


def canonical_id(ext: ExternalIds) -> str:
    """Stable cross-source key: DOI > s2 > openalex > arxiv."""
    if ext.doi:
        return norm_doi(ext.doi)
    if ext.s2:
        return f"s2:{ext.s2}"
    if ext.openalex:
        return f"oa:{norm_openalex(ext.openalex)}"
    if ext.arxiv:
        return f"arxiv:{norm_arxiv(ext.arxiv)}"
    raise ValueError("paper has no usable identifier")


def normalize_title(title: str) -> str:
    """Loose title key for dedup when DOIs are missing."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())
