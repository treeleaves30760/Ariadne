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
    return re.sub(r"^arxiv:", "", ax.strip(), flags=re.I) or None


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
