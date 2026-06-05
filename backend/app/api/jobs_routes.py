"""Routes for jobs, live progress (SSE), graph, reports, and export."""

from __future__ import annotations

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


class AskRequest(BaseModel):
    question: str


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
    return await db.list_jobs()


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
    return job


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
                event = await q.get()
                yield {"event": event.get("type", "message"), "data": json.dumps(event)}
                if event.get("type") in ("done", "failed"):
                    break
        finally:
            jobs.unsubscribe(job_id, q)

    return EventSourceResponse(gen())


@router.get("/{job_id}/graph")
async def job_graph(job_id: str, db: Database = Depends(get_database)):
    rows = await db.job_papers(job_id)
    edges = await db.job_edges(job_id)
    nodes = []
    for r in rows:
        p = await db.get_paper(r["paper_id"])
        if not p:
            continue
        summary = await db.get_summary(job_id, r["paper_id"])
        nodes.append({
            "id": p.id,
            "title": p.title,
            "year": p.year,
            "authors": [a.name for a in p.authors[:5]],
            "venue": p.venue,
            "citation_count": p.citation_count,
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
    codex = CodexClient(settings, max_calls=settings.max_codex_calls)
    try:
        result = await answer_question(
            codex, req.question, seed, list(papers.values()), summaries, job.params.language
        )
    except CodexBudgetExceeded:
        raise HTTPException(429, "Codex budget exhausted")
    result.created_at = datetime.now(timezone.utc).isoformat()
    await db.add_qa(job_id, result)
    return result
