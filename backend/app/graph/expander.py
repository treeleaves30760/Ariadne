"""Bidirectional BFS citation-graph expansion with Codex relevance filtering.

Per level: pull references/citations of the current frontier, dedup against what
we've already seen, cheaply prefilter to a budget, score relevance with Codex,
keep the most relevant (loose threshold + top-K), persist nodes/edges, then —
from depth 3 onward — summarize the kept papers and emit a progressive report.
A global node ceiling and the Codex call budget bound total cost; when a ceiling
truncates results we report it rather than truncating silently.

Each phase (fetch / score / summarize / report) is timed and logged, and the
cumulative per-phase breakdown is streamed to the UI so a slow run is diagnosable.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from app.ai.cluster import categorize_corpus
from app.ai.codex_client import CodexBudgetExceeded
from app.ai.relevance import score_relevance
from app.ai.report import generate_report, generate_web_context
from app.ai.summarize import summarize_papers
from app.config import Settings
from app.models import Edge, JobParams, Paper
from app.sources.merge import dedup_papers
from app.graph.prefilter import prefilter

log = logging.getLogger(__name__)

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
    async def upsert_clustering(self, job_id, clustering) -> None: ...


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
        self.node_level: dict[str, int] = {}      # id -> BFS level it was kept at
        self.summaries: dict[str, str] = {}
        self.all_links: list[tuple[str, str, str]] = []  # every (parent, neighbor, dir) seen
        self.fetched_refs: set[str] = set()       # ids whose reference list we've pulled
        self.node_count = 0
        self.notes: list[str] = []
        self.timings: dict[str, float] = {}       # cumulative seconds per phase
        self.start_time = time.monotonic()

    async def emit(self, **event) -> None:
        if self._emit:
            await self._emit(event)

    def _elapsed(self) -> float:
        return time.monotonic() - self.start_time

    @asynccontextmanager
    async def _timed(self, phase: str, level: int, detail: str = ""):
        """Time a phase: log + stream its start, accumulate the duration, then log + stream done."""
        head = f"L{level} {phase}" + (f" · {detail}" if detail else "")
        log.info("%s — start", head)
        await self.emit(type="progress", level=level, phase=phase, nodes=self.node_count,
                        codex_calls=self.codex.calls, elapsed_s=self._elapsed(), message=f"{head}…")
        t0 = time.monotonic()
        try:
            yield
        finally:
            dt = time.monotonic() - t0
            self.timings[phase] = self.timings.get(phase, 0.0) + dt
            log.info("%s — done in %.1fs (Σ%s=%.1fs, elapsed=%.0fs)",
                     head, dt, phase, self.timings[phase], self._elapsed())
            await self.emit(type="progress", level=level, phase=phase, nodes=self.node_count,
                            codex_calls=self.codex.calls, timings=dict(self.timings),
                            elapsed_s=self._elapsed(), message=f"{head} done in {dt:.1f}s")

    async def _record_node(self, paper: Paper, level: int, relevance: float, reason: str) -> None:
        await self.db.add_job_paper(self.job_id, paper.id, level, relevance, reason)
        self.visited.add(paper.id)
        self.kept_papers[paper.id] = paper
        self.node_level[paper.id] = level
        self.node_count += 1

    async def run(self) -> None:
        self.start_time = time.monotonic()
        log.info("expansion start: seed=%r depth=%d k=%d threshold=%.2f",
                 self.seed.title[:60], min(self.params.depth, self.settings.max_depth),
                 self.k, self.threshold)
        # Seed = level 0
        await self._record_node(self.seed, 0, 1.0, "seed")
        await self.emit(type="progress", level=0, nodes=self.node_count, edges=0,
                        codex_calls=self.codex.calls, elapsed_s=self._elapsed(),
                        message="seed added")

        frontier = [self.seed]
        depth = min(self.params.depth, self.settings.max_depth)

        for level in range(1, depth + 1):
            if self.node_count >= self.settings.max_nodes:
                self.notes.append(f"node ceiling {self.settings.max_nodes} reached before level {level}")
                await self.emit(type="note", message=self.notes[-1])
                break

            log.info("=== level %d/%d start (frontier=%d, nodes=%d, elapsed=%.0fs) ===",
                     level, depth, len(frontier), self.node_count, self._elapsed())
            await self.emit(type="progress", level=level, phase="expand", nodes=self.node_count,
                            codex_calls=self.codex.calls, elapsed_s=self._elapsed(),
                            message=f"expanding level {level}")

            async with self._timed("fetch", level, f"{len(frontier)} frontier paper(s)"):
                discovered, links = await self._gather(frontier, level)
            self.all_links.extend(links)  # keep every link for the cross-linking pass
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

            try:
                async with self._timed("score", level, f"{len(capped)} candidates"):
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
                if not paper:  # pragma: no cover - score_relevance only returns scored candidate ids
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

            log.info("L%d: kept %d/%d candidates, +%d edges (nodes now %d)",
                     level, len(new_frontier), len(capped), edge_count, self.node_count)
            await self.emit(type="progress", level=level, phase="kept", nodes=self.node_count,
                            edges=edge_count, codex_calls=self.codex.calls, elapsed_s=self._elapsed(),
                            message=f"level {level}: kept {len(new_frontier)} papers")

            # summaries for the newly kept papers
            if self.settings.summarize_kept and new_frontier and self.codex.remaining() > 0:
                try:
                    async with self._timed("summarize", level, f"{len(new_frontier)} papers"):
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

        # cross-link: connect papers that cite each other (turns the star into a real
        # graph and exposes foundational works via in-degree). Pure HTTP, no Codex.
        if self.settings.cross_link_enabled and len(self.kept_papers) > 1:
            await self._cross_link()

        # final synthesis
        final_report = None
        if self.codex.remaining() > 0:
            final_report = await self._make_report("final")

        # AI faceted categorization: organize the corpus into topical dimensions
        # so the map can be grouped/coloured by theme instead of a radial hairball.
        if self.settings.cluster_enabled and self.kept_papers and self.codex.remaining() > 0:
            await self._make_clusters()

        # external web context (DuckDuckGo) to extend report depth beyond the graph
        if self.settings.web_search_enabled and self.codex.remaining() > 0:
            gaps = final_report.gaps if final_report else []
            await self._make_web_report(gaps)

        log.info("expansion complete: %d nodes, %d Codex calls, %.0fs total; timings=%s",
                 self.node_count, self.codex.calls, self._elapsed(),
                 {k: round(v, 1) for k, v in self.timings.items()})
        await self.emit(type="done", nodes=self.node_count, codex_calls=self.codex.calls,
                        timings=dict(self.timings), elapsed_s=self._elapsed(), notes=self.notes)

    async def _gather(self, frontier: list[Paper], level: int):
        """Pull neighbors of the frontier; return (deduped papers, links)."""
        raw: list[Paper] = []
        links: list[tuple[str, str, str]] = []  # (parent_id, neighbor_id, direction)
        cap = self.settings.prefilter_per_paper
        for i, parent in enumerate(frontier, 1):
            short = parent.title[:60] + ("…" if len(parent.title) > 60 else "")
            await self.emit(type="activity", level=level, phase="fetch",
                            message=f"L{level}: fetching links of [{i}/{len(frontier)}] {short}")
            n_ref = n_cite = 0
            if self.params.include_references:
                refs = await self.library.get_neighbors(parent.id, "reference", cap, parent.external_ids)
                self.fetched_refs.add(parent.id)
                n_ref = len(refs)
                for r in refs:
                    raw.append(r)
                    links.append((parent.id, r.id, "reference"))
            if self.params.include_citations:
                cites = await self.library.get_neighbors(parent.id, "citation", cap, parent.external_ids)
                n_cite = len(cites)
                for c in cites:
                    raw.append(c)
                    links.append((parent.id, c.id, "citation"))
            log.info("L%d fetch [%d/%d] %s → %d refs, %d cites",
                     level, i, len(frontier), short, n_ref, n_cite)
        deduped = dedup_papers(raw)
        log.info("L%d fetch: %d raw neighbors → %d unique", level, len(raw), len(deduped))
        await self.emit(type="activity", level=level, phase="fetch",
                        message=f"L{level}: collected {len(deduped)} unique neighbors")
        return deduped, links

    async def _cross_link(self) -> None:
        """Connect kept papers that cite one another.

        Two passes: (1) replay every link we already fetched and keep the ones whose
        BOTH endpoints made it into the map; (2) for kept papers whose references we
        never pulled (the BFS leaves), fetch them now — capped — and link any that
        point at another kept paper. Edges are deduped by directed (src, dst) pair so
        a pair already linked (e.g. as a 'citation') isn't doubled as a 'reference'.
        """
        await self.emit(type="progress", phase="crosslink", nodes=self.node_count,
                        codex_calls=self.codex.calls, elapsed_s=self._elapsed(),
                        message="linking papers that cite each other")
        t0 = time.monotonic()
        existing = {(e.src, e.dst) for e in await self.db.job_edges(self.job_id)}

        async def _add(src: str, dst: str, direction: str) -> bool:
            if src == dst or (src, dst) in existing:
                return False
            await self.db.add_edge(self.job_id, Edge(
                src=src, dst=dst, direction=direction, level=self.node_level.get(src, 0)))
            existing.add((src, dst))
            return True

        added = 0
        # (1) edges among already-fetched papers that the per-level pass skipped
        for parent_id, neighbor_id, direction in self.all_links:
            if parent_id in self.visited and neighbor_id in self.visited:
                src, dst = ((parent_id, neighbor_id) if direction == "reference"
                            else (neighbor_id, parent_id))
                if await _add(src, dst, direction):
                    added += 1

        # (2) fetch references for kept leaves (most-cited first), capped
        leaves = [p for pid, p in self.kept_papers.items() if pid not in self.fetched_refs]
        leaves.sort(key=lambda p: p.citation_count or 0, reverse=True)
        cap = self.settings.cross_link_max_nodes
        if len(leaves) > cap:
            self.notes.append(f"cross-link: capped reference lookups {len(leaves)}→{cap}")
            await self.emit(type="note", message=self.notes[-1])
            leaves = leaves[:cap]
        for i, p in enumerate(leaves, 1):
            if i % 20 == 0 or i == len(leaves):
                await self.emit(type="activity", phase="crosslink",
                                message=f"cross-linking references [{i}/{len(leaves)}]")
            refs = await self.library.get_neighbors(
                p.id, "reference", self.settings.prefilter_per_paper, p.external_ids)
            for r in refs:
                if r.id in self.visited and await _add(p.id, r.id, "reference"):
                    added += 1

        self.timings["crosslink"] = self.timings.get("crosslink", 0.0) + (time.monotonic() - t0)
        log.info("cross-link — done in %.1fs, +%d internal edges", time.monotonic() - t0, added)
        await self.emit(type="links_ready", edges=added, nodes=self.node_count,
                        timings=dict(self.timings), elapsed_s=self._elapsed(),
                        message=f"linked {added} inter-paper citations")

    async def _make_report(self, level: str):
        log.info("report %s — start (%d papers)", level, len(self.kept_papers))
        await self.emit(type="reporting", level=level, phase="report", elapsed_s=self._elapsed(),
                        message=f"generating report {level}")
        papers = list(self.kept_papers.values())
        t0 = time.monotonic()
        try:
            report = await generate_report(
                self.codex, self.seed, papers, self.summaries, level, self.params.language
            )
        except CodexBudgetExceeded:
            self.notes.append(f"report {level}: budget exhausted, skipped")
            await self.emit(type="note", message=self.notes[-1])
            return None
        self.timings["report"] = self.timings.get("report", 0.0) + (time.monotonic() - t0)
        log.info("report %s — done in %.1fs", level, time.monotonic() - t0)
        await self.db.upsert_report(self.job_id, report)
        await self.emit(type="report_ready", level=level, codex_calls=self.codex.calls,
                        timings=dict(self.timings), elapsed_s=self._elapsed())
        return report

    async def _make_clusters(self) -> None:
        log.info("clustering — start (%d papers)", len(self.kept_papers))
        await self.emit(type="progress", phase="cluster", nodes=self.node_count,
                        codex_calls=self.codex.calls, elapsed_s=self._elapsed(),
                        message="organizing papers into dimensions")
        papers = list(self.kept_papers.values())
        t0 = time.monotonic()
        try:
            clustering = await categorize_corpus(
                self.codex, self.seed, papers, self.summaries,
                language=self.params.language,
                max_dimensions=self.settings.cluster_max_dimensions,
            )
        except CodexBudgetExceeded:
            self.notes.append("clustering: budget exhausted, skipped")
            await self.emit(type="note", message=self.notes[-1])
            return
        self.timings["cluster"] = self.timings.get("cluster", 0.0) + (time.monotonic() - t0)
        log.info("clustering — done in %.1fs (%d dimensions)",
                 time.monotonic() - t0, len(clustering.dimensions))
        await self.db.upsert_clustering(self.job_id, clustering)
        await self.emit(type="clusters_ready", dimensions=len(clustering.dimensions),
                        codex_calls=self.codex.calls, timings=dict(self.timings),
                        elapsed_s=self._elapsed())

    async def _make_web_report(self, gaps: list[str]) -> None:
        log.info("web report — start (%d gaps)", len(gaps))
        await self.emit(type="reporting", level="web", phase="web", elapsed_s=self._elapsed(),
                        message="searching the web (DuckDuckGo) for external context")
        await self.emit(type="activity", phase="web",
                        message="running web searches for surveys & recent work")
        t0 = time.monotonic()
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
        self.timings["web"] = self.timings.get("web", 0.0) + (time.monotonic() - t0)
        log.info("web report — done in %.1fs", time.monotonic() - t0)
        await self.db.upsert_report(self.job_id, report)
        await self.emit(type="report_ready", level="web", codex_calls=self.codex.calls,
                        timings=dict(self.timings), elapsed_s=self._elapsed())
