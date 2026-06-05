"""Export a job's papers as a BibTeX file or a Markdown reading list."""

from __future__ import annotations

import re

from app.models import Paper, Report


def _cite_key(p: Paper, used: set[str]) -> str:
    first_author = p.authors[0].name.split()[-1].lower() if p.authors else "anon"
    first_author = re.sub(r"[^a-z0-9]", "", first_author) or "anon"
    year = p.year or "n.d."
    base = f"{first_author}{year}"
    key = base
    i = 1
    while key in used:
        key = f"{base}{chr(ord('a') + i)}"
        i += 1
    used.add(key)
    return key


def _escape(text: str) -> str:
    return text.replace("{", "").replace("}", "")


def to_bibtex(papers: list[Paper]) -> str:
    used: set[str] = set()
    out: list[str] = []
    for p in papers:
        key = _cite_key(p, used)
        fields = [f"  title = {{{_escape(p.title)}}}"]
        if p.authors:
            fields.append("  author = {" + " and ".join(a.name for a in p.authors) + "}")
        if p.year:
            fields.append(f"  year = {{{p.year}}}")
        if p.venue:
            fields.append(f"  journal = {{{_escape(p.venue)}}}")
        if p.external_ids.doi:
            fields.append(f"  doi = {{{p.external_ids.doi}}}")
        if p.external_ids.arxiv:
            fields.append(f"  eprint = {{{p.external_ids.arxiv}}}")
        out.append("@article{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(out) + ("\n" if out else "")


def to_markdown(
    seed: Paper,
    rows: list[dict],
    papers: dict[str, Paper],
    summaries: dict[str, str],
    final_report: Report | None,
) -> str:
    lines = [f"# Reading list — {seed.title}", ""]
    if final_report and final_report.overview:
        lines += ["## Overview", "", final_report.overview, ""]

    must = set(final_report.must_reads) if final_report else set()
    if must:
        lines += ["## Must-read", ""]
        for pid in final_report.must_reads:
            p = papers.get(pid)
            if p:
                lines.append(_md_item(p, summaries.get(pid)))
        lines.append("")

    lines += ["## All papers by level", ""]
    by_level: dict[int, list[str]] = {}
    for r in rows:
        by_level.setdefault(r["level"], []).append(r["paper_id"])
    for level in sorted(by_level):
        label = "Seed" if level == 0 else f"Level {level}"
        lines += [f"### {label}", ""]
        for pid in by_level[level]:
            p = papers.get(pid)
            if p:
                lines.append(_md_item(p, summaries.get(pid)))
        lines.append("")
    return "\n".join(lines)


def _md_item(p: Paper, summary: str | None) -> str:
    authors = ", ".join(a.name for a in p.authors[:3])
    if len(p.authors) > 3:
        authors += " et al."
    year = f" ({p.year})" if p.year else ""
    link = f" — https://doi.org/{p.external_ids.doi}" if p.external_ids.doi else ""
    head = f"- **{p.title}**{year}. {authors}{link}"
    if summary:
        head += f"\n  - {summary}"
    return head
