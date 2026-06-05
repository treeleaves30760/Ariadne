"""Cheap, no-LLM candidate reduction before the (expensive) Codex relevance pass.

The point is only to bound how many candidates we pay Codex to score per level.
With the "loose" preset this cap is generous; ranking is by a cheap blend of
citation count and lexical overlap with the seed, so we drop the least promising
candidates first rather than truncating arbitrarily.
"""

from __future__ import annotations

import math

from app.models import Paper
from app.sources.ids import normalize_title

_STOP = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "via",
    "is", "are", "using", "based", "by", "from", "we", "our", "this", "that",
}


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_title(text).split() if t and t not in _STOP and len(t) > 2}


def _seed_terms(seed: Paper) -> set[str]:
    terms = _tokens(seed.title)
    if seed.abstract:
        terms |= _tokens(seed.abstract[:600])
    terms |= {normalize_title(f) for f in seed.fields_of_study}
    return terms


def cheap_score(paper: Paper, seed_terms: set[str]) -> float:
    overlap = len(_tokens(paper.title) & seed_terms)
    cites = math.log1p(paper.citation_count or 0)
    return overlap * 2.0 + cites


def prefilter(seed: Paper, candidates: list[Paper], cap: int) -> list[Paper]:
    """Return at most `cap` candidates, ranked by cheap relevance."""
    if len(candidates) <= cap:
        return candidates
    terms = _seed_terms(seed)
    ranked = sorted(candidates, key=lambda p: cheap_score(p, terms), reverse=True)
    return ranked[:cap]
