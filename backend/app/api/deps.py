"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.jobs.manager import JobManager
from app.services.library import PaperLibrary
from app.storage.db import Database, get_db


def get_library(request: Request) -> PaperLibrary:
    return request.app.state.library


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs


async def get_database() -> Database:
    return await get_db()
