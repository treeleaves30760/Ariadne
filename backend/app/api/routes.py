"""API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_database, get_library
from app.models import Paper, ResolveRequest, ResolveResponse, RuntimeConfig
from app.services.library import PaperLibrary
from app.storage.db import Database

router = APIRouter()

# Models the user may select (model + reasoning effort), surfaced to the frontend.
AVAILABLE_MODELS = ["gpt-5.5", "gpt-5.4"]
REASONING_EFFORTS = ["low", "medium", "high", "xhigh"]


def _mask_key(key: str | None) -> str | None:
    if not key:
        return None
    return f"…{key[-4:]}" if len(key) > 4 else "****"


@router.get("/settings")
async def get_settings_route(db: Database = Depends(get_database)):
    cfg = await db.get_runtime_config()
    return {
        "model": cfg.model,
        "reasoning_effort": cfg.reasoning_effort,
        "api_base": cfg.api_base,
        "api_key_set": bool(cfg.api_key),
        "api_key_masked": _mask_key(cfg.api_key),
        "available_models": AVAILABLE_MODELS,
        "reasoning_efforts": REASONING_EFFORTS,
    }


@router.put("/settings")
async def put_settings_route(cfg: RuntimeConfig, db: Database = Depends(get_database)):
    current = await db.get_runtime_config()
    # Keep the stored key if the client sends back the masked placeholder / blank.
    if not cfg.api_key or cfg.api_key.startswith("…"):
        cfg.api_key = current.api_key
    if cfg.model and cfg.model not in AVAILABLE_MODELS:
        raise HTTPException(400, f"unsupported model: {cfg.model}")
    if cfg.reasoning_effort and cfg.reasoning_effort not in REASONING_EFFORTS:
        raise HTTPException(400, f"unsupported reasoning effort: {cfg.reasoning_effort}")
    await db.set_runtime_config(cfg)
    return {"ok": True}


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
