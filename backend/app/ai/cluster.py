"""Codex-powered faceted categorization of the corpus into topical dimensions.

Instead of every paper hanging off the seed in one radial burst, we ask Codex to
organize the collected papers into a handful of topic-specific *dimensions*
(facets) — e.g. "Benchmarks & Datasets", "Core Methods", "Applications". Each
paper gets a primary dimension (drives colour + grouping in the graph) plus
optional secondary tags, since a paper often relates to the seed along several
axes. The result lets the UI lay the map out by theme and colour-code it, which
is far more legible than a hairball of citation edges.

`build_clustering` is a pure function of the model's JSON, so the messy
normalization (id slugging, label resolution, the "Other" fallback) is unit-
testable without invoking Codex.
"""

from __future__ import annotations

import logging
import re

from app.ai.codex_client import CodexClient
from app.ai.relevance import seed_profile
from app.ai.summarize import LANGUAGE_NAMES
from app.models import Clustering, Dimension, Paper, PaperFacet

log = logging.getLogger(__name__)

# Dark-theme palette, distinct hues; deliberately excludes the seed pink (#f7768e).
PALETTE = [
    "#6ea8fe", "#5ec8a6", "#f0a868", "#b692f6", "#e0af68", "#7dcfff",
    "#9ece6a", "#ff9e64", "#bb9af7", "#73daca", "#7aa2f7", "#c0caf5",
]
OTHER_COLOR = "#5a6577"

CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["label", "description"],
                "additionalProperties": False,
            },
        },
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "primary": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["paper_id", "primary", "tags"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["dimensions", "assignments"],
    "additionalProperties": False,
}


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s[:40] or "dim"


def _match_id(value: str, valid: set[str]) -> str | None:
    """Map a model-returned paper reference back to a real id (tolerant match)."""
    if value in valid:
        return value
    hits = [vid for vid in valid if vid in value]
    return max(hits, key=len) if hits else None  # longest wins (avoids prefix collisions)


def _render(p: Paper, summary: str | None) -> str:
    yr = f" ({p.year})" if p.year else ""
    s = (summary or p.tldr or (p.abstract or ""))[:200]
    return f"- id: {p.id} | {p.title}{yr}\n  {s}"


def build_prompt(
    seed: Paper, papers: list[Paper], summaries: dict[str, str], language: str, max_dimensions: int
) -> str:
    lang = LANGUAGE_NAMES.get(language, "English")
    block = "\n".join(_render(p, summaries.get(p.id)) for p in papers)
    return (
        "You are organizing a citation-graph corpus for a PhD student into a small set of "
        f"topical DIMENSIONS (facets) — at most {max_dimensions}. Good dimensions describe how "
        "papers relate to the SEED along distinct axes, e.g. 'Benchmarks & Datasets', "
        "'Core Methods', 'Applications', 'Theory & Analysis', 'Surveys'. Pick dimensions that fit "
        "THIS corpus specifically; make them clear and minimally overlapping.\n\n"
        f"Write each dimension's label and description in {lang}.\n\n"
        f"SEED:\n{seed_profile(seed)}\n\n"
        f"PAPERS ({len(papers)}):\n{block}\n\n"
        "Then assign EVERY paper to exactly one primary dimension (its best fit) and optionally "
        "up to 3 secondary tags naming other dimensions it also touches. Use the exact paper_id "
        "given. `primary` and each tag MUST be one of the dimension labels you defined above."
    )


def build_clustering(data: dict, papers: list[Paper], max_dimensions: int) -> Clustering:
    """Normalize the model's raw JSON into a validated Clustering.

    Slugs dimension ids, resolves assignment labels back to those ids, drops
    duplicates/unknowns, and sweeps any unassigned paper into an "Other" bucket
    so every node always carries a primary dimension.
    """
    valid = {p.id for p in papers}
    dims: list[Dimension] = []
    by_label: dict[str, str] = {}   # lower(label) -> dimension id
    used_ids: set[str] = set()
    for d in (data.get("dimensions") or [])[:max_dimensions]:
        label = (d.get("label") or "").strip()
        if not label or label.lower() in by_label:
            continue
        did = base = _slug(label)
        n = 2
        while did in used_ids:      # disambiguate slug collisions ("X" / "X!" -> x, x-2)
            did = f"{base}-{n}"
            n += 1
        used_ids.add(did)
        dims.append(Dimension(
            id=did, label=label, description=(d.get("description") or "").strip(),
            color=PALETTE[len(dims) % len(PALETTE)],
        ))
        by_label[label.lower()] = did

    def resolve(label: str) -> str | None:
        key = (label or "").strip().lower()
        if not key:
            return None
        if key in by_label:
            return by_label[key]
        hits = [v for k, v in by_label.items() if k in key or key in k]
        return hits[0] if hits else None

    facets: list[PaperFacet] = []
    assigned: dict[str, str] = {}
    for a in data.get("assignments") or []:
        pid = _match_id(a.get("paper_id") or "", valid)
        if not pid or pid in assigned:
            continue
        primary = resolve(a.get("primary") or "")
        if not primary:
            continue
        tags: list[str] = []
        for t in a.get("tags") or []:
            tid = resolve(t)
            if tid and tid != primary and tid not in tags:
                tags.append(tid)
        facets.append(PaperFacet(paper_id=pid, primary=primary, tags=tags))
        assigned[pid] = primary

    # Papers the model skipped (or mapped to an unknown dimension) → "Other".
    missing = [pid for pid in valid if pid not in assigned]
    if missing:
        dims.append(Dimension(id="other", label="Other", color=OTHER_COLOR,
                              description="Papers that didn't fit a named dimension."))
        for pid in missing:
            facets.append(PaperFacet(paper_id=pid, primary="other"))

    # Backfill each dimension's members from the facets; drop empty dimensions.
    members: dict[str, list[str]] = {}
    for f in facets:
        members.setdefault(f.primary, []).append(f.paper_id)
    for d in dims:
        d.paper_ids = members.get(d.id, [])
    dims = [d for d in dims if d.paper_ids]
    return Clustering(level="final", dimensions=dims, facets=facets)


async def categorize_corpus(
    codex: CodexClient,
    seed: Paper,
    papers: list[Paper],
    summaries: dict[str, str],
    language: str = "en",
    *,
    max_dimensions: int = 8,
) -> Clustering:
    """Ask Codex to group the corpus (seed excluded) into dimensions."""
    items = [p for p in papers if p.id != seed.id]
    if not items:
        return Clustering(dimensions=[], facets=[])
    log.info("clustering %d papers into ≤%d dimensions", len(items), max_dimensions)
    data = await codex.run_structured(
        build_prompt(seed, items, summaries, language, max_dimensions), CLUSTER_SCHEMA
    )
    return build_clustering(data or {}, items, max_dimensions)
