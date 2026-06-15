"""arXiv Atom API adapter.

Direct arXiv access so freshly-posted papers (not yet indexed by Semantic
Scholar / OpenAlex) and explicit arXiv-id / DOI lookups resolve immediately.
arXiv returns Atom XML, so this adapter uses the fetcher's ``get_text`` and
parses with the stdlib XML parser.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import httpx

from app.config import Settings
from app.models import Author, Candidate, ExternalIds, Paper
from app.sources.http import HttpFetcher, Throttle
from app.sources.ids import arxiv_from_doi, canonical_id, norm_arxiv, norm_doi
from app.storage.db import Database

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return " ".join(node.text.split()) or None


def _arxiv_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"arxiv\.org/abs/(.+)$", url.strip(), flags=re.I)
    return norm_arxiv(m.group(1)) if m else None


class Arxiv:
    name = "arxiv"

    def __init__(self, fetcher: HttpFetcher, settings: Settings):
        self.f = fetcher
        self.base = settings.arxiv_base

    @classmethod
    def build(cls, client: httpx.AsyncClient, settings: Settings, db: Database) -> "Arxiv":
        fetcher = HttpFetcher(
            client,
            Throttle(settings.arxiv_min_interval_s),
            db=db,
            max_retries=settings.http_max_retries,
            source="arxiv",
        )
        return cls(fetcher, settings)

    # ---------------------------- conversion ----------------------------- #
    @staticmethod
    def _entry_to_paper(entry: ET.Element) -> Paper | None:
        title = _text(entry.find(f"{_ATOM}title"))
        ax_id = _arxiv_id_from_url(_text(entry.find(f"{_ATOM}id")))
        if not title or not ax_id:
            return None
        # Prefer a publisher DOI; otherwise the standard arXiv DataCite DOI, which
        # OpenAlex also assigns — so the same paper dedups across sources.
        journal_doi = norm_doi(_text(entry.find(f"{_ARXIV}doi")))
        synth = f"10.48550/arxiv.{ax_id}" if re.fullmatch(r"\d{4}\.\d{4,5}", ax_id) else None
        published = _text(entry.find(f"{_ATOM}published")) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            Author(name=name)
            for a in entry.findall(f"{_ATOM}author")
            if (name := _text(a.find(f"{_ATOM}name")))
        ]
        pdf_url = None
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
        primary = entry.find(f"{_ARXIV}primary_category")
        fos = [primary.get("term")] if primary is not None and primary.get("term") else []
        ext = ExternalIds(doi=journal_doi or synth, arxiv=ax_id)
        return Paper(
            id=canonical_id(ext),
            title=title,
            abstract=_text(entry.find(f"{_ATOM}summary")),
            year=year,
            authors=authors,
            venue="arXiv",
            citation_count=None,
            fields_of_study=fos,
            external_ids=ext,
            url=f"https://arxiv.org/abs/{ax_id}",
            pdf_url=pdf_url,
            sources=["arxiv"],
        )

    def _parse(self, xml: str | None) -> list[Paper]:
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []
        out: list[Paper] = []
        for entry in root.findall(f"{_ATOM}entry"):
            p = self._entry_to_paper(entry)
            if p:
                out.append(p)
        return out

    # ------------------------------- API --------------------------------- #
    async def search(self, query: str, limit: int = 10) -> list[Candidate]:
        # Drop Lucene-significant punctuation; arXiv's `all:` field does the rest.
        terms = re.sub(r"[^\w\s]", " ", query).split()
        if not terms:
            return []
        xml = await self.f.get_text(
            f"{self.base}/query",
            params={"search_query": "all:" + " ".join(terms),
                    "start": 0, "max_results": min(limit, 25)},
            ok_404=True,
        )
        return [_paper_to_candidate(p) for p in self._parse(xml)]

    async def get_paper(self, canonical: str, ext: ExternalIds | None = None) -> Paper | None:
        if ext and ext.arxiv:
            ax_id = norm_arxiv(ext.arxiv)
        elif canonical.startswith("arxiv:"):
            ax_id = norm_arxiv(canonical[6:])
        else:
            ax_id = arxiv_from_doi(canonical if canonical.startswith("10.") else (ext.doi if ext else None))
        if not ax_id:
            return None
        xml = await self.f.get_text(
            f"{self.base}/query", params={"id_list": ax_id, "max_results": 1}, ok_404=True
        )
        papers = self._parse(xml)
        return papers[0] if papers else None


def _paper_to_candidate(p: Paper) -> Candidate:
    return Candidate(
        id=p.id,
        title=p.title,
        year=p.year,
        authors=[a.name for a in p.authors[:5]],
        venue=p.venue,
        citation_count=p.citation_count,
        source="arxiv",
        external_ids=p.external_ids,
    )
