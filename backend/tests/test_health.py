"""Smoke tests for app wiring and storage."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Job, JobParams, JobProgress, Paper


def test_health():
    with TestClient(create_app()) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


async def test_paper_roundtrip(db):
    paper = Paper(id="10.1/x", title="Attention Is All You Need", year=2017)
    await db.upsert_paper(paper)
    got = await db.get_paper("10.1/x")
    assert got is not None
    assert got.title == "Attention Is All You Need"


async def test_job_roundtrip(db):
    job = Job(
        id="job1",
        params=JobParams(seed_id="10.1/x", depth=3),
        progress=JobProgress(),
        created_at="2026-06-05T00:00:00Z",
    )
    await db.create_job(job)
    job.progress.nodes = 5
    await db.update_job(job)
    got = await db.get_job("job1")
    assert got is not None
    assert got.progress.nodes == 5
    assert got.params.depth == 3
