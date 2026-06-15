"""Routes for jobs, live progress (SSE), graph, reports, and export."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.ai.codex_client import CodexBudgetExceeded, CodexClient
from app.ai.qa import answer_question
from app.api.deps import get_database, get_jobs
from app.config import get_settings
from app.jobs.manager import TERMINAL, JobManager
from app.models import Job, JobParams, QAResult
from app.services.export import to_bibtex, to_markdown
from app.storage.db import Database

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Seconds of silence on a live SSE stream before we emit a liveness "heartbeat"
# and re-check whether the worker is still running. Module-level so tests can
# shrink it; short enough that proxies don't idle the connection out.
HEARTBEAT_S = 15


class AskRequest(BaseModel):
    question: str
    use_tools: bool = True   # let the assistant search the web + read PDFs to verify


class RenameRequest(BaseModel):
    name: str


async def _with_seed_title(db: Database, job: Job) -> Job:
    """Attach the seed paper's title (used as the default map label) when known."""
    paper = await db.get_paper(job.params.seed_id)
    if paper:
        job.seed_title = paper.title
    return job


async def _load_corpus(db: Database, job_id: str):
    """Return (rows, papers_by_id, summaries_by_id) for a job."""
    rows = await db.job_papers(job_id)
    papers: dict[str, object] = {}
    summaries: dict[str, str] = {}
    for r in rows:
        p = await db.get_paper(r["paper_id"])
        if p:
            papers[p.id] = p
        sm = await db.get_summary(job_id, r["paper_id"])
        if sm:
            summaries[r["paper_id"]] = sm.text
    return rows, papers, summaries


@router.get("", response_model=list[Job])
async def list_jobs(db: Database = Depends(get_database)):
    jobs = await db.list_jobs()
    for job in jobs:
        await _with_seed_title(db, job)
    return jobs


@router.post("", response_model=Job)
async def create_job(params: JobParams, jobs: JobManager = Depends(get_jobs)):
    job = await jobs.create_job(params)
    jobs.start_job(job.id)
    return job


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str, db: Database = Depends(get_database)):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return await _with_seed_title(db, job)


@router.patch("/{job_id}", response_model=Job)
async def rename_job(job_id: str, req: RenameRequest, db: Database = Depends(get_database)):
    """Set a custom label for a map (blank clears it, reverting to the seed title)."""
    if not await db.rename_job(job_id, req.name.strip() or None):
        raise HTTPException(404, "job not found")
    job = await db.get_job(job_id)
    return await _with_seed_title(db, job)


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: Database = Depends(get_database)):
    """Permanently delete a map and all its data (papers, edges, reports, summaries, Q&A)."""
    if not await db.delete_job(job_id):
        raise HTTPException(404, "job not found")
    return {"ok": True}


@router.get("/{job_id}/events")
async def job_events(
    job_id: str, jobs: JobManager = Depends(get_jobs), db: Database = Depends(get_database)
):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    async def gen():
        # initial snapshot
        yield {"event": "snapshot", "data": job.progress.model_dump_json()}
        if job.progress.status in TERMINAL:
            yield {"event": "end", "data": json.dumps({"status": job.progress.status})}
            return
        q = jobs.subscribe(job_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    # No progress event for a while (e.g. a long Codex call). Tell the
                    # client whether we're still alive or the worker is gone, so it
                    # never has to guess "disconnected" vs "still generating".
                    if jobs.is_running(job_id):
                        yield {"event": "heartbeat", "data": json.dumps({"status": "alive"})}
                        continue
                    fresh = await db.get_job(job_id)
                    st = fresh.progress.status if fresh else None
                    if st in TERMINAL:
                        # finished between events — surface the final state, then stop
                        yield {"event": "end", "data": json.dumps({"status": st})}
                    else:
                        # task vanished (e.g. server restart) but status non-terminal
                        yield {"event": "stale", "data": json.dumps({"status": st})}
                    break
                yield {"event": event.get("type", "message"), "data": json.dumps(event)}
                if event.get("type") in ("done", "failed"):
                    break
        finally:
            jobs.unsubscribe(job_id, q)

    return EventSourceResponse(gen())


@router.get("/{job_id}/graph")
async def job_graph(job_id: str, db: Database = Depends(get_database)):
    from app.services.scoring import importance_score, is_top_venue, max_log_cites

    rows = await db.job_papers(job_id)
    edges = await db.job_edges(job_id)
    papers = {}
    for r in rows:
        p = await db.get_paper(r["paper_id"])
        if p:
            papers[r["paper_id"]] = p
    mlc = max_log_cites([p.citation_count for p in papers.values()])

    nodes = []
    for r in rows:
        p = papers.get(r["paper_id"])
        if not p:
            continue
        summary = await db.get_summary(job_id, r["paper_id"])
        top = is_top_venue(p.venue)
        nodes.append({
            "id": p.id,
            "title": p.title,
            "year": p.year,
            "authors": [a.name for a in p.authors[:5]],
            "venue": p.venue,
            "citation_count": p.citation_count,
            "top_venue": top,
            "importance": importance_score(r["relevance"], p.citation_count, top, mlc),
            "url": p.url,
            "pdf_url": p.pdf_url,
            "external_ids": p.external_ids.model_dump(),
            "level": r["level"],
            "relevance": r["relevance"],
            "reason": r["reason"],
            "summary": summary.text if summary else None,
        })
    return {
        "nodes": nodes,
        "edges": [e.model_dump() for e in edges],
    }


@router.get("/{job_id}/reports")
async def job_reports(job_id: str, db: Database = Depends(get_database)):
    levels = await db.list_reports(job_id)
    order = {"3": 0, "4": 1, "5": 2, "final": 3}
    return {"levels": sorted(levels, key=lambda l: order.get(l, 99))}


@router.get("/{job_id}/reports/{level}")
async def job_report(job_id: str, level: str, db: Database = Depends(get_database)):
    report = await db.get_report(job_id, level)
    if not report:
        raise HTTPException(404, "report not found")
    return report


@router.get("/{job_id}/export")
async def export(
    job_id: str,
    format: Literal["bibtex", "markdown"] = "markdown",
    db: Database = Depends(get_database),
):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    rows = await db.job_papers(job_id)
    papers = {}
    summaries = {}
    for r in rows:
        p = await db.get_paper(r["paper_id"])
        if p:
            papers[p.id] = p
        sm = await db.get_summary(job_id, r["paper_id"])
        if sm:
            summaries[r["paper_id"]] = sm.text

    ordered = [papers[r["paper_id"]] for r in rows if r["paper_id"] in papers]
    if format == "bibtex":
        return PlainTextResponse(to_bibtex(ordered), media_type="text/plain")

    seed = papers.get(job.params.seed_id) or (ordered[0] if ordered else None)
    if not seed:
        raise HTTPException(404, "no papers for job")
    final_report = await db.get_report(job_id, "final")
    md = to_markdown(seed, rows, papers, summaries, final_report)
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/{job_id}/qa", response_model=list[QAResult])
async def qa_history(job_id: str, db: Database = Depends(get_database)):
    return await db.list_qa(job_id)


@router.post("/{job_id}/ask", response_model=QAResult)
async def ask(job_id: str, req: AskRequest, db: Database = Depends(get_database)):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not req.question.strip():
        raise HTTPException(400, "question is required")

    _, papers, summaries = await _load_corpus(db, job_id)
    if not papers:
        raise HTTPException(409, "no papers collected yet for this job")
    seed = papers.get(job.params.seed_id) or next(iter(papers.values()))

    settings = get_settings()
    rt = await db.get_runtime_config()
    codex = CodexClient(settings, max_calls=settings.max_codex_calls, runtime=rt)
    try:
        result = await answer_question(
            codex, req.question, seed, list(papers.values()), summaries,
            job.params.language, history=await db.list_qa(job_id), use_tools=req.use_tools,
            web_max=settings.web_search_max_results,
        )
    except CodexBudgetExceeded:
        raise HTTPException(429, "Codex budget exhausted")
    result.created_at = datetime.now(timezone.utc).isoformat()
    await db.add_qa(job_id, result)
    return result
