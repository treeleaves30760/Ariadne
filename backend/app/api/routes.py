"""API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_database, get_library
from app.models import Paper, ResolveRequest, ResolveResponse
from app.services.library import PaperLibrary
from app.storage.db import Database

router = APIRouter()


@router.post("/resolve", response_model=ResolveResponse)
async def resolve(req: ResolveRequest, library: PaperLibrary = Depends(get_library)):
    candidates = await library.resolve(req.query, req.limit)
    return ResolveResponse(candidates=candidates)


@router.get("/papers/{paper_id:path}", response_model=Paper)
async def get_paper(
    paper_id: str,
    library: PaperLibrary = Depends(get_library),
    db: Database = Depends(get_database),
):
    cached = await db.get_paper(paper_id)
    if cached:
        return cached
    paper = await library.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    return paper


@router.get("/neighbors")
async def neighbors(
    paper_id: str,
    direction: Literal["reference", "citation"] = "reference",
    limit: int = 50,
    library: PaperLibrary = Depends(get_library),
):
    papers = await library.get_neighbors(paper_id, direction, limit)
    return {"direction": direction, "count": len(papers), "papers": papers}
