"""Merge / dedup papers and candidates across sources."""

from __future__ import annotations

from app.models import Candidate, ExternalIds, Paper
from app.sources.ids import canonical_id, normalize_title


def dedup_key(p: Paper | Candidate) -> str:
    """Key papers across sources: DOI if present, else normalized title."""
    if p.external_ids.doi:
        return f"doi:{p.external_ids.doi}"
    return f"title:{normalize_title(p.title)}"


def _merge_ext(a: ExternalIds, b: ExternalIds) -> ExternalIds:
    return ExternalIds(
        doi=a.doi or b.doi,
        arxiv=a.arxiv or b.arxiv,
        s2=a.s2 or b.s2,
        openalex=a.openalex or b.openalex,
    )


def merge_papers(papers: list[Paper]) -> Paper:
    """Combine source variants of the same paper into one canonical record.

    S2 is preferred for abstract/tldr; fields are filled from whichever source has them.
    The canonical id is recomputed (DOI wins) from the merged identifiers.
    """
    if not papers:
        raise ValueError("merge_papers requires at least one paper")
    # Order: S2 first so its abstract/tldr win.
    ordered = sorted(papers, key=lambda p: 0 if "s2" in p.sources else 1)
    base = ordered[0]
    ext = base.external_ids
    for p in ordered[1:]:
        ext = _merge_ext(ext, p.external_ids)

    def pick(attr: str):
        for p in ordered:
            v = getattr(p, attr)
            if v:
                return v
        return getattr(base, attr)

    from app.sources.ids import canonical_id

    sources: list[str] = []
    for p in ordered:
        for s in p.sources:
            if s not in sources:
                sources.append(s)

    return Paper(
        id=canonical_id(ext),
        title=pick("title"),
        abstract=pick("abstract"),
        tldr=pick("tldr"),
        year=pick("year"),
        authors=pick("authors") or base.authors,
        venue=pick("venue"),
        citation_count=max((p.citation_count or 0) for p in ordered) or None,
        fields_of_study=pick("fields_of_study") or [],
        external_ids=ext,
        url=pick("url"),
        pdf_url=pick("pdf_url"),
        sources=sources,
    )


def dedup_papers(papers: list[Paper]) -> list[Paper]:
    """Merge a flat list of papers that may contain cross-source duplicates."""
    buckets: dict[str, list[Paper]] = {}
    order: list[str] = []
    for p in papers:
        k = dedup_key(p)
        if k not in buckets:
            buckets[k] = []
            order.append(k)
        buckets[k].append(p)
    return [merge_papers(buckets[k]) for k in order]


def dedup_candidates(*lists: list[Candidate]) -> list[Candidate]:
    """Merge candidate lists from multiple sources, preferring the richer entry."""
    buckets: dict[str, Candidate] = {}
    order: list[str] = []
    for lst in lists:
        for c in lst:
            k = dedup_key(c)
            if k not in buckets:
                buckets[k] = c
                order.append(k)
            else:
                existing = buckets[k]
                # prefer the one with more metadata / higher citation count
                ext = _merge_ext(existing.external_ids, c.external_ids)
                better = c if (c.citation_count or 0) > (existing.citation_count or 0) else existing
                # Recompute the canonical id from the merged ids (DOI wins) so the
                # survivor stays addressable across sources (e.g. an arXiv paper keeps
                # its DOI/arXiv routing instead of an unaddressable OpenAlex-only id).
                buckets[k] = better.model_copy(
                    update={"external_ids": ext, "id": canonical_id(ext)}
                )
    return [buckets[k] for k in order]


def collapse_by_title(cands: list[Candidate]) -> list[Candidate]:
    """Second-pass merge: fold candidates that share a normalized title.

    ``dedup_candidates`` keys on DOI-or-title, so two records of the same paper
    where only one carries a DOI stay separate (e.g. OpenAlex sometimes indexes
    an arXiv paper twice — once with its DataCite DOI, once without). This folds
    them together, unioning identifiers and keeping the higher citation count.
    """
    buckets: dict[str, Candidate] = {}
    order: list[str] = []
    for c in cands:
        k = normalize_title(c.title)
        if k not in buckets:
            buckets[k] = c
            order.append(k)
        else:
            existing = buckets[k]
            ext = _merge_ext(existing.external_ids, c.external_ids)
            better = c if (c.citation_count or 0) > (existing.citation_count or 0) else existing
            buckets[k] = better.model_copy(
                update={"external_ids": ext, "id": canonical_id(ext)}
            )
    return [buckets[k] for k in order]
