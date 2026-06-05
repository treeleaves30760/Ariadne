"""Unit tests for BibTeX / Markdown export."""

from __future__ import annotations

from app.models import Author, ExternalIds, Paper, Report
from app.services.export import to_bibtex, to_markdown


def _p(pid, title, year, author, doi=None):
    return Paper(id=pid, title=title, year=year, authors=[Author(name=author)],
                 external_ids=ExternalIds(doi=doi))


def test_to_bibtex_keys_and_fields():
    papers = [
        _p("10/a", "Paper A", 2017, "Ashish Vaswani", doi="10/a"),
        _p("10/b", "Paper B", 2017, "Jacob Devlin", doi="10/b"),
    ]
    bib = to_bibtex(papers)
    assert "@article{vaswani2017," in bib
    assert "title = {Paper A}" in bib
    assert "doi = {10/a}" in bib


def test_to_bibtex_dedupes_keys():
    papers = [
        _p("10/a", "A", 2020, "Smith", doi="10/a"),
        _p("10/b", "B", 2020, "Smith", doi="10/b"),
    ]
    bib = to_bibtex(papers)
    assert "@article{smith2020," in bib
    assert "@article{smith2020b," in bib


def test_to_markdown_structure():
    seed = _p("10/seed", "Seed", 2017, "Author", doi="10/seed")
    papers = {"10/seed": seed, "10/a": _p("10/a", "Paper A", 2018, "Vaswani", doi="10/a")}
    rows = [
        {"paper_id": "10/seed", "level": 0, "relevance": 1.0, "reason": ""},
        {"paper_id": "10/a", "level": 1, "relevance": 0.9, "reason": ""},
    ]
    report = Report(level="final", overview="An overview.", must_reads=["10/a"])
    md = to_markdown(seed, rows, papers, {"10/a": "Key paper."}, report)
    assert "# Reading list — Seed" in md
    assert "## Overview" in md
    assert "## Must-read" in md
    assert "Key paper." in md
    assert "### Level 1" in md
