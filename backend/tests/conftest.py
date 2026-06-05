"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.storage.db import Database


@pytest.fixture
async def db() -> Database:
    """In-memory database for isolated tests."""
    database = await Database.connect(":memory:")
    yield database
    await database.close()
