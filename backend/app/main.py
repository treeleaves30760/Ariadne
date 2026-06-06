"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.jobs.manager import JobManager
from app.services.library import PaperLibrary
from app.storage.db import close_db, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await get_db()  # connect + create schema on startup
    settings = get_settings()
    app.state.library = PaperLibrary.build(db, settings)
    app.state.jobs = JobManager(db, app.state.library, settings)
    try:
        yield
    finally:
        await app.state.library.aclose()
        await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Ariadne", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    # Routers are registered here as milestones land.
    from app.api.jobs_routes import router as jobs_router
    from app.api.routes import router as api_router

    app.include_router(api_router)
    app.include_router(jobs_router)

    return app


app = create_app()
