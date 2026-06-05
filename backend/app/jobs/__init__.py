"""Background job orchestration (in-process asyncio + SQLite persistence)."""

from app.jobs.manager import JobManager

__all__ = ["JobManager"]
