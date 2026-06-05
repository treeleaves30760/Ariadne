"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.services.library import PaperLibrary
from app.storage.db import Database, get_db


def get_library(request: Request) -> PaperLibrary:
    return request.app.state.library


async def get_database() -> Database:
    return await get_db()
