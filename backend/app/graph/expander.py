"""Bidirectional BFS citation-graph expansion with Codex relevance filtering.

Per level: pull references/citations of the current frontier, dedup against what
we've already seen, cheaply prefilter to a budget, score relevance with Codex,
keep the most relevant (loose threshold + top-K), persist nodes/edges, then —
from depth 3 onward — summarize the kept papers and emit a progressive report.
A global node ceiling and the Codex call budget bound total cost; when a ceiling
truncates results we report it rather than truncating silently.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.ai.codex_client import CodexBudgetExceeded
from app.ai.relevance import score_relevance
from app.ai.report import generate_report, generate_web_context
from app.ai.summarize import summarize_papers
from app.config import Settings
from app.models import Edge, JobParams, Paper
from app.sources.merge import dedup_papers
from app.graph.prefilter import prefilter

Emit = Callable[[dict], Awaitable[None]]


class LibraryLike(Protocol):
    async def get_neighbors(self, canonical: str, direction: str, limit: int, ext=None) -> list[Paper]: ...


class CodexLike(Protocol):
    @property
    def calls(self) -> int: ...
    def remaining(self) -> int: ...
    async def run_structured(self, prompt: str, schema: dict, *, model=None): ...


class DBLike(Protocol):
    async def add_job_paper(self, job_id, paper_id, level, relevance, reason) -> None: ...
    async def add_edge(self, job_id, edge: Edge) -> None: ...
    async def upsert_summary(self, job_id, summary) -> None: ...
    async def upsert_report(self, job_id, report) -> None: ...


class GraphExpander:
    def __init__(
        self,
        job_id: str,
        seed: Paper,
        params: JobParams,
        *,
        library: LibraryLike,
        codex: CodexLike,
        db: DBLike,
        settings: Settings,
        emit: Emit | None = None,
    ):
        self.job_id = job_id
        self.seed = seed
        self.params = params
        self.library = library
        self.codex = codex
        self.db = db
        self.settings = settings
        self._emit = emit
        self.k = params.per_level_k or settings.per_level_k
        self.threshold = (
            params.relevance_threshold
            if params.relevance_threshold is not None
            else settings.relevance_threshold
        )
        self.visited: set[str] = set()
        self.kept_papers: dict[str, Paper] = {}   # id -> paper (all kept incl. seed)
        self.summaries: dict[str, str] = {}
        self.node_count = 0
        self.notes: list[str] = []

    async def emit(self, **event) -> None:
        if self._emit:
            await self._emit(event)

    async def _record_node(self, paper: Paper, level: int, relevance: float, reason: str) -> None:
        await self.db.add_job_paper(self.job_id, paper.id, level, relevance, reason)
        self.visited.add(paper.id)
        self.kept_papers[paper.id] = paper
        self.node_count += 1

    async def run(self) -> None:
        # Seed = level 0
        await self._record_node(self.seed, 0, 1.0, "seed")
        await self.emit(type="progress", level=0, nodes=self.node_count, edges=0,
                        codex_calls=self.codex.calls, message="seed added")

        frontier = [self.seed]
        depth = min(self.params.depth, self.settings.max_depth)

        for level in range(1, depth + 1):
            if self.node_count >= self.settings.max_nodes:
                self.notes.append(f"node ceiling {self.settings.max_nodes} reached before level {level}")
                await self.emit(type="note", message=self.notes[-1])
                break

            await self.emit(type="progress", level=level, nodes=self.node_count,
                            codex_calls=self.codex.calls, message=f"expanding level {level}")

            discovered, links = await self._gather(frontier, level)
            fresh = [p for p in discovered if p.id not in self.visited]
            if not fresh:
                await self.emit(type="note", message=f"level {level}: no new candidates")
                break

            capped = prefilter(self.seed, fresh, self.settings.max_candidates_per_level)
            if len(capped) < len(fresh):
                self.notes.append(
                    f"level {level}: prefiltered {len(fresh)}→{len(capped)} candidates before scoring"
                )
                await self.emit(type="note", message=self.notes[-1])

            await self.emit(type="activity", level=level,
                            message=f"L{level}: scoring {len(capped)} candidates for relevance (Codex)")
            try:
                scored = await score_relevance(
                    self.codex, self.seed, capped, self.settings.relevance_batch_size
                )
            except CodexBudgetExceeded:
                self.notes.append(f"level {level}: Codex budget exhausted; stopping expansion")
                await self.emit(type="note", message=self.notes[-1])
                break

            by_id = {p.id: p for p in capped}
            kept = sorted(
                (s for s in scored if s.relevance >= self.threshold),
                key=lambda s: s.relevance,
                reverse=True,
            )[: self.k]

            # global node ceiling
            room = self.settings.max_nodes - self.node_count
            if len(kept) > room:
                self.notes.append(
                    f"level {level}: node ceiling trims {len(kept)}→{room} kept papers"
                )
                await self.emit(type="note", message=self.notes[-1])
                kept = kept[:room]

            kept_ids = set()
            new_frontier: list[Paper] = []
            for s in kept:
                paper = by_id.get(s.paper_id)
                if not paper:
                    continue
                await self._record_node(paper, level, s.relevance, s.reason)
                kept_ids.add(paper.id)
                new_frontier.append(paper)

            # persist edges only between graph nodes
            edge_count = 0
            for parent_id, neighbor_id, direction in links:
                if neighbor_id in kept_ids and parent_id in self.visited:
                    await self.db.add_edge(
                        self.job_id,
                        Edge(src=parent_id if direction == "reference" else neighbor_id,
                             dst=neighbor_id if direction == "reference" else parent_id,
                             direction=direction, level=level),
                    )
                    edge_count += 1

            await self.emit(type="progress", level=level, nodes=self.node_count, edges=edge_count,
                            codex_calls=self.codex.calls,
                            message=f"level {level}: kept {len(new_frontier)} papers")

            # summaries for the newly kept papers
            if self.settings.summarize_kept and new_frontier and self.codex.remaining() > 0:
                await self.emit(type="activity", level=level,
                                message=f"L{level}: writing AI summaries for {len(new_frontier)} papers")
                try:
                    sums = await summarize_papers(
                        self.codex, self.seed, new_frontier, self.params.language
                    )
                    for sm in sums:
                        self.summaries[sm.paper_id] = sm.text
                        await self.db.upsert_summary(self.job_id, sm)
                except CodexBudgetExceeded:
                    self.notes.append(f"level {level}: budget hit before summaries")
                    await self.emit(type="note", message=self.notes[-1])

            # progressive report from depth 3 onward
            if level >= 3 and self.codex.remaining() > 0:
                await self._make_report(str(level))

            frontier = new_frontier
            if not frontier:
                break

        # final synthesis
        final_report = None
        if self.codex.remaining() > 0:
            final_report = await self._make_report("final")

        # external web context (DuckDuckGo) to extend report depth beyond the graph
        if self.settings.web_search_enabled and self.codex.remaining() > 0:
            gaps = final_report.gaps if final_report else []
            await self._make_web_report(gaps)

        await self.emit(type="done", nodes=self.node_count, codex_calls=self.codex.calls,
                        notes=self.notes)

    async def _gather(self, frontier: list[Paper], level: int):
        """Pull neighbors of the frontier; return (deduped papers, links)."""
        raw: list[Paper] = []
        links: list[tuple[str, str, str]] = []  # (parent_id, neighbor_id, direction)
        cap = self.settings.prefilter_per_paper
        for i, parent in enumerate(frontier, 1):
            short = parent.title[:60] + ("…" if len(parent.title) > 60 else "")
            await self.emit(type="activity", level=level,
                            message=f"L{level}: fetching links of [{i}/{len(frontier)}] {short}")
            if self.params.include_references:
                refs = await self.library.get_neighbors(parent.id, "reference", cap, parent.external_ids)
                for r in refs:
                    raw.append(r)
                    links.append((parent.id, r.id, "reference"))
            if self.params.include_citations:
                cites = await self.library.get_neighbors(parent.id, "citation", cap, parent.external_ids)
                for c in cites:
                    raw.append(c)
                    links.append((parent.id, c.id, "citation"))
        deduped = dedup_papers(raw)
        await self.emit(type="activity", level=level,
                        message=f"L{level}: collected {len(deduped)} unique neighbors")
        return deduped, links

    async def _make_report(self, level: str):
        await self.emit(type="reporting", level=level, message=f"generating report {level}")
        papers = list(self.kept_papers.values())
        try:
            report = await generate_report(
                self.codex, self.seed, papers, self.summaries, level, self.params.language
            )
        except CodexBudgetExceeded:
            self.notes.append(f"report {level}: budget exhausted, skipped")
            await self.emit(type="note", message=self.notes[-1])
            return None
        await self.db.upsert_report(self.job_id, report)
        await self.emit(type="report_ready", level=level, codex_calls=self.codex.calls)
        return report

    async def _make_web_report(self, gaps: list[str]) -> None:
        await self.emit(type="reporting", level="web",
                        message="searching the web (DuckDuckGo) for external context")
        await self.emit(type="activity", message="running web searches for surveys & recent work")
        try:
            report = await generate_web_context(
                self.codex, self.seed, gaps,
                language=self.params.language,
                max_results=self.settings.web_search_max_results,
                max_queries=self.settings.web_search_max_queries,
            )
        except CodexBudgetExceeded:
            self.notes.append("web report: budget exhausted, skipped")
            await self.emit(type="note", message=self.notes[-1])
            return
        await self.db.upsert_report(self.job_id, report)
        await self.emit(type="report_ready", level="web", codex_calls=self.codex.calls)
