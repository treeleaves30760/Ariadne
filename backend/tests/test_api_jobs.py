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


async def test_settings_roundtrip_and_key_masking(populated_db):
    with _client(populated_db) as client:
        # set model + effort + key
        r = client.put("/settings", json={
            "model": "gpt-5.5", "reasoning_effort": "high",
            "api_base": "https://api.example.com/v1", "api_key": "sk-secret-1234",
        })
        assert r.status_code == 200
        s = client.get("/settings").json()
        assert s["model"] == "gpt-5.5"
        assert s["reasoning_effort"] == "high"
        assert s["api_key_set"] is True
        assert s["api_key_masked"] == "…1234"     # key never returned in full
        assert "gpt-5.4" in s["available_models"]
        assert "xhigh" in s["reasoning_efforts"]
        # rejects unsupported values
        assert client.put("/settings", json={"model": "gpt-3"}).status_code == 400
        # blank api_key keeps the existing one
        client.put("/settings", json={"model": "gpt-5.4", "api_key": ""})
        assert client.get("/settings").json()["api_key_set"] is True


async def test_graph_has_importance(populated_db):
    with _client(populated_db) as client:
        data = client.get("/jobs/job1/graph").json()
        child = next(n for n in data["nodes"] if n["id"] == "10/a")
        assert "importance" in child and 0.0 <= child["importance"] <= 1.0
        assert "top_venue" in child


async def test_graph_has_degree_and_foundational(populated_db):
    # populated_db has the edge 10/seed → 10/a (seed references child)
    with _client(populated_db) as client:
        nodes = {n["id"]: n for n in client.get("/jobs/job1/graph").json()["nodes"]}
        seed, child = nodes["10/seed"], nodes["10/a"]
        assert child["in_degree"] == 1 and child["out_degree"] == 0
        assert seed["out_degree"] == 1 and seed["in_degree"] == 0
        # child is cited within the corpus → more foundational than the (uncited) seed
        assert child["foundational"] > seed["foundational"]
        assert 0.0 <= child["foundational"] <= 1.0


async def test_list_jobs(populated_db):
    with _client(populated_db) as client:
        jobs = client.get("/jobs").json()
        assert any(j["id"] == "job1" for j in jobs)


async def test_list_jobs_includes_seed_title(populated_db):
    with _client(populated_db) as client:
        jobs = client.get("/jobs").json()
        job1 = next(j for j in jobs if j["id"] == "job1")
        assert job1["seed_title"] == "Seed"


async def test_rename_job(populated_db):
    with _client(populated_db) as client:
        resp = client.patch("/jobs/job1", json={"name": "My favourite map"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "My favourite map"
        # persisted across a fresh read
        job1 = next(j for j in client.get("/jobs").json() if j["id"] == "job1")
        assert job1["name"] == "My favourite map"


async def test_rename_job_blank_clears_name(populated_db):
    with _client(populated_db) as client:
        client.patch("/jobs/job1", json={"name": "Temp"})
        resp = client.patch("/jobs/job1", json={"name": "   "})
        assert resp.status_code == 200
        assert resp.json()["name"] is None


async def test_rename_missing_job_404(populated_db):
    with _client(populated_db) as client:
        assert client.patch("/jobs/nope", json={"name": "x"}).status_code == 404


async def test_delete_job_removes_job_and_data(populated_db):
    with _client(populated_db) as client:
        assert client.delete("/jobs/job1").status_code == 200
        # the job itself is gone
        assert client.get("/jobs/job1").status_code == 404
        assert all(j["id"] != "job1" for j in client.get("/jobs").json())
        # and its associated rows (papers, edges, reports, summaries) are gone too
        assert client.get("/jobs/job1/graph").json()["nodes"] == []
        assert client.get("/jobs/job1/reports").json()["levels"] == []


async def test_delete_missing_job_404(populated_db):
    with _client(populated_db) as client:
        assert client.delete("/jobs/nope").status_code == 404


async def test_ask_endpoint(populated_db, monkeypatch):
    from app.models import QAResult

    async def fake_answer(codex, question, seed, papers, summaries, language="en", **kw):
        return QAResult(question=question, answer="Grounded answer.",
                        citations=["10/a"], confidence=0.8)

    monkeypatch.setattr("app.api.jobs_routes.answer_question", fake_answer)
    with _client(populated_db) as client:
        resp = client.post("/jobs/job1/ask", json={"question": "What is A about?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Grounded answer."
        assert data["citations"] == ["10/a"]
        # persisted to history
        hist = client.get("/jobs/job1/qa").json()
        assert len(hist) == 1 and hist[0]["question"] == "What is A about?"


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
