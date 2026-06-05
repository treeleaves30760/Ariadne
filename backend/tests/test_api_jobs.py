"""API tests for job routes using dependency overrides + a pre-populated DB."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_database, get_jobs
from app.main import create_app
from app.models import (
    Author,
    Edge,
    ExternalIds,
    Job,
    JobParams,
    Paper,
    Report,
    Summary,
)
from app.storage.db import Database


@pytest.fixture
async def populated_db() -> Database:
    db = await Database.connect(":memory:")
    seed = Paper(id="10/seed", title="Seed", year=2017,
                 authors=[Author(name="Vaswani")], external_ids=ExternalIds(doi="10/seed"))
    child = Paper(id="10/a", title="Child A", year=2018,
                  authors=[Author(name="Devlin")], external_ids=ExternalIds(doi="10/a"))
    await db.upsert_paper(seed)
    await db.upsert_paper(child)
    job = Job(id="job1", params=JobParams(seed_id="10/seed", depth=3), created_at="2026-06-05T00:00Z")
    await db.create_job(job)
    await db.add_job_paper("job1", "10/seed", 0, 1.0, "seed")
    await db.add_job_paper("job1", "10/a", 1, 0.9, "core method")
    await db.add_edge("job1", Edge(src="10/seed", dst="10/a", direction="reference", level=1))
    await db.upsert_summary("job1", Summary(paper_id="10/a", text="A key paper.", language="en"))
    await db.upsert_report("job1", Report(level="final", overview="Overview.", must_reads=["10/a"]))
    yield db
    await db.close()


def _client(db) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_database] = lambda: db
    return TestClient(app)


async def test_graph_endpoint(populated_db):
    with _client(populated_db) as client:
        resp = client.get("/jobs/job1/graph")
        assert resp.status_code == 200
        data = resp.json()
        ids = {n["id"] for n in data["nodes"]}
        assert ids == {"10/seed", "10/a"}
        child = next(n for n in data["nodes"] if n["id"] == "10/a")
        assert child["summary"] == "A key paper."
        assert child["relevance"] == 0.9
        assert data["edges"][0]["direction"] == "reference"


async def test_reports_endpoints(populated_db):
    with _client(populated_db) as client:
        assert client.get("/jobs/job1/reports").json()["levels"] == ["final"]
        report = client.get("/jobs/job1/reports/final").json()
        assert report["overview"] == "Overview."
        assert client.get("/jobs/job1/reports/3").status_code == 404


async def test_export_endpoints(populated_db):
    with _client(populated_db) as client:
        bib = client.get("/jobs/job1/export", params={"format": "bibtex"}).text
        assert "@article{" in bib and "Seed" in bib
        md = client.get("/jobs/job1/export", params={"format": "markdown"}).text
        assert "# Reading list — Seed" in md
        assert "A key paper." in md


async def test_create_job_starts_it(populated_db):
    started = {}

    class FakeJobs:
        async def create_job(self, params):
            return Job(id="newjob", params=params, created_at="2026-06-05T00:00Z")

        def start_job(self, job_id):
            started["id"] = job_id

    app = create_app()
    app.dependency_overrides[get_database] = lambda: populated_db
    app.dependency_overrides[get_jobs] = lambda: FakeJobs()
    with TestClient(app) as client:
        resp = client.post("/jobs", json={"seed_id": "10/seed", "depth": 3})
        assert resp.status_code == 200
        assert resp.json()["id"] == "newjob"
    assert started["id"] == "newjob"
