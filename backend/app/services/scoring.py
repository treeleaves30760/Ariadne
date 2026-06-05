"""Paper importance scoring.

Combines three signals a PhD student cares about:
  - relevance  : Codex similarity of the paper to the seed topic (0..1)
  - impact     : citation count (log-normalized within the job)
  - venue      : whether it appeared at a recognized top venue
"""

from __future__ import annotations

import math

# Recognized top venues / publishers (matched case-insensitively as substrings).
TOP_VENUES = {
    # ML / AI
    "neural information processing", "neurips", "nips",
    "international conference on machine learning", "icml",
    "international conference on learning representations", "iclr",
    "aaai", "ijcai",
    # NLP
    "annual meeting of the association for computational linguistics", "acl",
    "empirical methods in natural language processing", "emnlp",
    "naacl", "conference of the european chapter", "eacl", "coling",
    "transactions of the association for computational linguistics", "tacl",
    # Vision
    "computer vision and pattern recognition", "cvpr",
    "international conference on computer vision", "iccv",
    "european conference on computer vision", "eccv",
    # Systems / data / web / KDD
    "knowledge discovery and data mining", "sigkdd", "kdd",
    "the web conference", "www", "sigir", "wsdm", "sigmod", "vldb",
    # General science
    "nature", "science", "proceedings of the national academy",
    # ML theory / general
    "journal of machine learning research", "jmlr",
    "pattern analysis and machine intelligence", "tpami",
}


def is_top_venue(venue: str | None) -> bool:
    if not venue:
        return False
    v = venue.lower()
    return any(t in v for t in TOP_VENUES)


def importance_score(
    relevance: float | None,
    citation_count: int | None,
    top_venue: bool,
    max_log_cites: float,
) -> float:
    """Blend relevance, log-normalized citations, and a top-venue bonus into 0..1."""
    rel = relevance if relevance is not None else 0.0
    log_c = math.log1p(citation_count or 0)
    cites_norm = (log_c / max_log_cites) if max_log_cites > 0 else 0.0
    venue_bonus = 1.0 if top_venue else 0.0
    score = 0.45 * rel + 0.40 * cites_norm + 0.15 * venue_bonus
    return round(min(1.0, max(0.0, score)), 3)


def max_log_cites(citation_counts: list[int | None]) -> float:
    vals = [math.log1p(c or 0) for c in citation_counts]
    return max(vals) if vals else 0.0
