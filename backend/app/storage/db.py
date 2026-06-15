"""SQLite storage layer.

A thin async wrapper over aiosqlite. Complex objects are stored as JSON text
keyed by id; relational lookups we actually need (edges by job, papers by job)
get their own columns/indexes.
"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from app.config import get_settings
from app.models import (
    Clustering,
    Edge,
    Job,
    JobParams,
    JobProgress,
    Paper,
    QAResult,
    Report,
    RuntimeConfig,
    Summary,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_papers (
    job_id      TEXT NOT NULL,
    paper_id    TEXT NOT NULL,
    level       INTEGER NOT NULL,
    relevance   REAL,
    reason      TEXT,
    PRIMARY KEY (job_id, paper_id)
);
CREATE INDEX IF NOT EXISTS ix_job_papers_job ON job_papers(job_id);

CREATE TABLE IF NOT EXISTS edges (
    job_id      TEXT NOT NULL,
    src         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    direction   TEXT NOT NULL,
    level       INTEGER NOT NULL,
    PRIMARY KEY (job_id, src, dst, direction)
);
CREATE INDEX IF NOT EXISTS ix_edges_job ON edges(job_id);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    params      TEXT NOT NULL,
    progress    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    error       TEXT,
    name        TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    job_id      TEXT NOT NULL,
    paper_id    TEXT NOT NULL,
    language    TEXT NOT NULL,
    text        TEXT NOT NULL,
    PRIMARY KEY (job_id, paper_id, language)
);

CREATE TABLE IF NOT EXISTS reports (
    job_id      TEXT NOT NULL,
    level       TEXT NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (job_id, level)
);

CREATE TABLE IF NOT EXISTS clusters (
    job_id      TEXT PRIMARY KEY,
    data        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_cache (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qa (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    data        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_qa_job ON qa(job_id);

CREATE TABLE IF NOT EXISTS settings (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    data        TEXT NOT NULL
);
"""


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    @classmethod
    async def connect(cls, path: str) -> "Database":
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.executescript(SCHEMA)
        await conn.commit()
        db = cls(conn)
        await db._migrate()
        return db

    async def _migrate(self) -> None:
        """Additive, idempotent migrations for DBs created before a column existed."""
        cur = await self._conn.execute("PRAGMA table_info(jobs)")
        cols = {r["name"] for r in await cur.fetchall()}
        if "name" not in cols:
            await self._conn.execute("ALTER TABLE jobs ADD COLUMN name TEXT")
            await self._conn.commit()

    async def close(self) -> None:
        await self._conn.close()

    # ----------------------------- api cache ----------------------------- #
    async def cache_get(self, key: str) -> Any | None:
        cur = await self._conn.execute("SELECT value FROM api_cache WHERE key = ?", (key,))
        row = await cur.fetchone()
        return json.loads(row["value"]) if row else None

    async def cache_set(self, key: str, value: Any) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO api_cache (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        await self._conn.commit()

    # ------------------------------ papers ------------------------------- #
    async def upsert_paper(self, paper: Paper) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO papers (id, data) VALUES (?, ?)",
            (paper.id, paper.model_dump_json()),
        )
        await self._conn.commit()

    async def get_paper(self, paper_id: str) -> Paper | None:
        cur = await self._conn.execute("SELECT data FROM papers WHERE id = ?", (paper_id,))
        row = await cur.fetchone()
        return Paper.model_validate_json(row["data"]) if row else None

    # --------------------------- job <-> papers -------------------------- #
    async def add_job_paper(
        self, job_id: str, paper_id: str, level: int, relevance: float | None, reason: str
    ) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO job_papers (job_id, paper_id, level, relevance, reason)"
            " VALUES (?, ?, ?, ?, ?)",
            (job_id, paper_id, level, relevance, reason),
        )
        await self._conn.commit()

    async def job_papers(self, job_id: str) -> list[dict[str, Any]]:
        cur = await self._conn.execute(
            "SELECT paper_id, level, relevance, reason FROM job_papers WHERE job_id = ?"
            " ORDER BY level, relevance DESC",
            (job_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def add_edge(self, job_id: str, edge: Edge) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO edges (job_id, src, dst, direction, level)"
            " VALUES (?, ?, ?, ?, ?)",
            (job_id, edge.src, edge.dst, edge.direction, edge.level),
        )
        await self._conn.commit()

    async def job_edges(self, job_id: str) -> list[Edge]:
        cur = await self._conn.execute(
            "SELECT src, dst, direction, level FROM edges WHERE job_id = ?", (job_id,)
        )
        return [Edge(**dict(r)) for r in await cur.fetchall()]

    # ------------------------------- jobs -------------------------------- #
    async def create_job(self, job: Job) -> None:
        await self._conn.execute(
            "INSERT INTO jobs (id, params, progress, created_at, error, name)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                job.id,
                job.params.model_dump_json(),
                job.progress.model_dump_json(),
                job.created_at,
                job.error,
                job.name,
            ),
        )
        await self._conn.commit()

    async def update_job(self, job: Job) -> None:
        await self._conn.execute(
            "UPDATE jobs SET progress = ?, error = ? WHERE id = ?",
            (job.progress.model_dump_json(), job.error, job.id),
        )
        await self._conn.commit()

    async def rename_job(self, job_id: str, name: str | None) -> bool:
        """Set (or clear, when name is None) a job's custom label. False if no such job."""
        cur = await self._conn.execute(
            "UPDATE jobs SET name = ? WHERE id = ?", (name, job_id)
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def delete_job(self, job_id: str) -> bool:
        """Permanently delete a job and all rows that reference it. False if no such job."""
        cur = await self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        for tbl in ("job_papers", "edges", "summaries", "reports", "clusters", "qa"):
            await self._conn.execute(f"DELETE FROM {tbl} WHERE job_id = ?", (job_id,))
        await self._conn.commit()
        return cur.rowcount > 0

    async def get_job(self, job_id: str) -> Job | None:
        cur = await self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        if not row:
            return None
        return Job(
            id=row["id"],
            params=JobParams.model_validate_json(row["params"]),
            progress=JobProgress.model_validate_json(row["progress"]),
            created_at=row["created_at"],
            error=row["error"],
            name=row["name"],
        )

    # ----------------------------- summaries ----------------------------- #
    async def upsert_summary(self, job_id: str, summary: Summary) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO summaries (job_id, paper_id, language, text)"
            " VALUES (?, ?, ?, ?)",
            (job_id, summary.paper_id, summary.language, summary.text),
        )
        await self._conn.commit()

    async def get_summary(self, job_id: str, paper_id: str) -> Summary | None:
        cur = await self._conn.execute(
            "SELECT paper_id, language, text FROM summaries WHERE job_id = ? AND paper_id = ?",
            (job_id, paper_id),
        )
        row = await cur.fetchone()
        return Summary(**dict(row)) if row else None

    # ------------------------------ reports ------------------------------ #
    async def upsert_report(self, job_id: str, report: Report) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO reports (job_id, level, data) VALUES (?, ?, ?)",
            (job_id, report.level, report.model_dump_json()),
        )
        await self._conn.commit()

    async def get_report(self, job_id: str, level: str) -> Report | None:
        cur = await self._conn.execute(
            "SELECT data FROM reports WHERE job_id = ? AND level = ?", (job_id, level)
        )
        row = await cur.fetchone()
        return Report.model_validate_json(row["data"]) if row else None

    async def list_reports(self, job_id: str) -> list[str]:
        cur = await self._conn.execute(
            "SELECT level FROM reports WHERE job_id = ?", (job_id,)
        )
        return [r["level"] for r in await cur.fetchall()]

    # ------------------------------ clusters ----------------------------- #
    async def upsert_clustering(self, job_id: str, clustering: Clustering) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO clusters (job_id, data) VALUES (?, ?)",
            (job_id, clustering.model_dump_json()),
        )
        await self._conn.commit()

    async def get_clustering(self, job_id: str) -> Clustering | None:
        cur = await self._conn.execute(
            "SELECT data FROM clusters WHERE job_id = ?", (job_id,)
        )
        row = await cur.fetchone()
        return Clustering.model_validate_json(row["data"]) if row else None

    # -------------------------------- qa --------------------------------- #
    async def add_qa(self, job_id: str, qa: "QAResult") -> None:
        await self._conn.execute(
            "INSERT INTO qa (job_id, data, created_at) VALUES (?, ?, ?)",
            (job_id, qa.model_dump_json(), qa.created_at),
        )
        await self._conn.commit()

    async def list_qa(self, job_id: str) -> list["QAResult"]:
        cur = await self._conn.execute(
            "SELECT data FROM qa WHERE job_id = ? ORDER BY id", (job_id,)
        )
        return [QAResult.model_validate_json(r["data"]) for r in await cur.fetchall()]

    # --------------------------- runtime config -------------------------- #
    async def get_runtime_config(self) -> "RuntimeConfig":
        cur = await self._conn.execute("SELECT data FROM settings WHERE id = 1")
        row = await cur.fetchone()
        return RuntimeConfig.model_validate_json(row["data"]) if row else RuntimeConfig()

    async def set_runtime_config(self, cfg: "RuntimeConfig") -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
            (cfg.model_dump_json(),),
        )
        await self._conn.commit()

    # ----------------------------- job list ------------------------------ #
    async def list_jobs(self, limit: int = 50) -> list[Job]:
        cur = await self._conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        jobs = []
        for row in await cur.fetchall():
            jobs.append(Job(
                id=row["id"],
                params=JobParams.model_validate_json(row["params"]),
                progress=JobProgress.model_validate_json(row["progress"]),
                created_at=row["created_at"],
                error=row["error"],
                name=row["name"],
            ))
        return jobs


_db: Database | None = None


async def get_db() -> Database:
    """FastAPI dependency: return the process-wide Database, connecting lazily."""
    global _db
    if _db is None:
        settings = get_settings()
        _db = await Database.connect(str(settings.db_file))
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
