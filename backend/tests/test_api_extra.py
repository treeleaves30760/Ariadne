"""Coverage for API routes (settings/resolve/paper/neighbors), deps, and job SSE/ask/export edges."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.deps as deps
from app.api.deps import get_database, get_jobs, get_library
from app.api.jobs_routes import job_events
from app.main import create_app
from app.models import Candidate, ExternalIds, Job, JobParams, JobStatus, Paper
from app.storage.db import Database


# -------------------------------- routes --------------------------------- #
class FakeLib:
    def __init__(self, candidates=None, paper=None, neighbors=None):
        self._c = candidates or []
        self._p = paper
        self._n = neighbors or []

    async def resolve(self, query, limit=10):
        return self._c

    async def get_paper(self, canonical, ext=None):
        return self._p

    async def get_neighbors(self, canonical, direction, limit, ext=None):
        return self._n


def _client(db, lib=None):
    app = create_app()
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_library] = lambda: (lib or FakeLib())
    return TestClient(app)


async def test_settings_short_key_masked():
    db = await Database.connect(":memory:")
    try:
        with _client(db) as c:
            c.put("/settings", json={"api_key": "abcd"})
            assert c.get("/settings").json()["api_key_masked"] == "****"
    finally:
        await db.close()


async def test_settings_rejects_bad_reasoning_effort():
    db = await Database.connect(":memory:")
    try:
        with _client(db) as c:
            assert c.put("/settings", json={"reasoning_effort": "ultra"}).status_code == 400
    finally:
        await db.close()


async def test_settings_no_key_masked_is_none():
    db = await Database.connect(":memory:")
    try:
        with _client(db) as c:
            s = c.get("/settings").json()
            assert s["api_key_set"] is False
            assert s["api_key_masked"] is None
    finally:
        await db.close()


async def test_resolve_route():
    db = await Database.connect(":memory:")
    cand = Candidate(id="10/a", title="A", source="s2", external_ids=ExternalIds(doi="10/a"))
    try:
        with _client(db, FakeLib(candidates=[cand])) as c:
            r = c.post("/resolve", json={"query": "x", "limit": 5})
            assert r.status_code == 200 and r.json()["candidates"][0]["id"] == "10/a"
    finally:
        await db.close()


async def test_get_paper_cached_fetched_and_404():
    db = await Database.connect(":memory:")
    await db.upsert_paper(Paper(id="10/seed", title="Cached", external_ids=ExternalIds(doi="10/seed")))
    try:
        with _client(db) as c:  # cached path
            assert c.get("/papers/10/seed").json()["title"] == "Cached"
        fetched = Paper(id="10/new", title="Fetched", external_ids=ExternalIds(doi="10/new"))
        with _client(db, FakeLib(paper=fetched)) as c:  # fetched path
            assert c.get("/papers/10/new").json()["title"] == "Fetched"
        with _client(db, FakeLib(paper=None)) as c:  # 404 path
            assert c.get("/papers/10/missing").status_code == 404
    finally:
        await db.close()


async def test_neighbors_route():
    db = await Database.connect(":memory:")
    nb = Paper(id="10/n", title="N", external_ids=ExternalIds(doi="10/n"))
    try:
        with _client(db, FakeLib(neighbors=[nb])) as c:
            r = c.get("/neighbors", params={"paper_id": "10/seed", "direction": "reference", "limit": 10})
            assert r.json()["count"] == 1 and r.json()["papers"][0]["id"] == "10/n"
    finally:
        await db.close()


# --------------------------------- deps ---------------------------------- #
def test_get_library_and_jobs_from_state():
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(library="LIB", jobs="JOBS")))
    assert get_library(req) == "LIB"
    assert get_jobs(req) == "JOBS"


async def test_get_database_returns_singleton(monkeypatch):
    async def fake_get_db():
        return "DB"

    monkeypatch.setattr(deps, "get_db", fake_get_db)
    assert await deps.get_database() == "DB"


# ------------------------------- jobs edges ------------------------------ #
async def _seeded():
    db = await Database.connect(":memory:")
    await db.upsert_paper(Paper(id="10/seed", title="Seed", external_ids=ExternalIds(doi="10/seed")))
    await db.create_job(Job(id="j1", params=JobParams(seed_id="10/seed"), created_at="t"))
    await db.add_job_paper("j1", "10/seed", 0, 1.0, "seed")
    return db


def _jobs_client(db):
    app = create_app()
    app.dependency_overrides[get_database] = lambda: db
    return TestClient(app)


async def test_get_job_includes_seed_title_and_404():
    db = await _seeded()
    try:
        with _jobs_client(db) as c:
            assert c.get("/jobs/j1").json()["seed_title"] == "Seed"
            assert c.get("/jobs/missing").status_code == 404
    finally:
        await db.close()


async def test_graph_skips_papers_missing_from_store():
    db = await _seeded()
    await db.add_job_paper("j1", "ghost", 1, 0.5, "x")  # no papers row for "ghost"
    try:
        with _jobs_client(db) as c:
            ids = {n["id"] for n in c.get("/jobs/j1/graph").json()["nodes"]}
            assert "ghost" not in ids and "10/seed" in ids
    finally:
        await db.close()


async def test_export_missing_job_and_no_papers():
    db = await _seeded()
    empty = await Database.connect(":memory:")
    await empty.create_job(Job(id="empty", params=JobParams(seed_id="10/x"), created_at="t"))
    try:
        with _jobs_client(db) as c:
            assert c.get("/jobs/missing/export").status_code == 404
        with _jobs_client(empty) as c:
            assert c.get("/jobs/empty/export", params={"format": "markdown"}).status_code == 404
    finally:
        await db.close()
        await empty.close()


async def test_ask_validation_paths():
    db = await _seeded()
    empty = await Database.connect(":memory:")
    await empty.create_job(Job(id="np", params=JobParams(seed_id="10/x"), created_at="t"))
    try:
        with _jobs_client(db) as c:
            assert c.post("/jobs/missing/ask", json={"question": "q"}).status_code == 404
            assert c.post("/jobs/j1/ask", json={"question": "   "}).status_code == 400
        with _jobs_client(empty) as c:
            assert c.post("/jobs/np/ask", json={"question": "q"}).status_code == 409
    finally:
        await db.close()
        await empty.close()


async def test_ask_budget_exhausted_returns_429(monkeypatch):
    import app.api.jobs_routes as jr
    from app.ai.codex_client import CodexBudgetExceeded

    db = await _seeded()

    async def boom(*a, **k):
        raise CodexBudgetExceeded("budget")

    monkeypatch.setattr(jr, "answer_question", boom)
    try:
        with _jobs_client(db) as c:
            assert c.post("/jobs/j1/ask", json={"question": "q", "use_tools": False}).status_code == 429
    finally:
        await db.close()


async def test_events_404():
    db = await Database.connect(":memory:")
    try:
        with _jobs_client(db) as c:
            assert c.get("/jobs/none/events").status_code == 404
    finally:
        await db.close()


async def test_events_terminal_job_emits_snapshot_and_end():
    db = await Database.connect(":memory:")
    job = Job(id="done1", params=JobParams(seed_id="10/x"), created_at="t")
    job.progress.status = JobStatus.completed
    await db.create_job(job)
    try:
        with _jobs_client(db) as c:
            r = c.get("/jobs/done1/events")
            assert r.status_code == 200
            assert "snapshot" in r.text and "end" in r.text
    finally:
        await db.close()


async def test_events_streams_until_terminal_event():
    db = await Database.connect(":memory:")
    job = Job(id="run1", params=JobParams(seed_id="10/x"), created_at="t")
    job.progress.status = JobStatus.expanding
    await db.create_job(job)

    q: asyncio.Queue = asyncio.Queue()
    await q.put({"type": "progress", "message": "working"})
    await q.put({"type": "done", "nodes": 2})

    class FakeJobs:
        def __init__(self):
            self.unsubscribed = False

        def subscribe(self, jid):
            return q

        def unsubscribe(self, jid, qq):
            self.unsubscribed = True

    fj = FakeJobs()
    resp = await job_events(job_id="run1", jobs=fj, db=db)
    events = [chunk async for chunk in resp.body_iterator]
    text = " ".join(str(e) for e in events)
    try:
        assert "snapshot" in text and "progress" in text and "done" in text
        assert fj.unsubscribed
    finally:
        await db.close()


# ------------------- SSE heartbeat / liveness edges ---------------------- #
class _Jobs:
    """Minimal JobManager stand-in for SSE liveness tests."""

    def __init__(self, q, running):
        self.q = q
        self.running = running
        self.unsubscribed = False

    def subscribe(self, jid):
        return self.q

    def unsubscribe(self, jid, qq):
        self.unsubscribed = True

    def is_running(self, jid):
        return self.running


class _SeqDB:
    """get_job returns successive statuses: [route-entry, in-loop re-check]."""

    def __init__(self, statuses):
        self._statuses = list(statuses)

    async def get_job(self, jid):
        st = self._statuses.pop(0)
        job = Job(id=jid, params=JobParams(seed_id="10/x"), created_at="t")
        job.progress.status = st
        return job


async def test_events_heartbeat_while_worker_alive(db, monkeypatch):
    import app.api.jobs_routes as jr
    monkeypatch.setattr(jr, "HEARTBEAT_S", 0.01)
    job = Job(id="hb", params=JobParams(seed_id="10/x"), created_at="t")
    job.progress.status = JobStatus.expanding
    await db.create_job(job)

    q: asyncio.Queue = asyncio.Queue()
    fj = _Jobs(q, running=True)
    resp = await job_events(job_id="hb", jobs=fj, db=db)
    it = resp.body_iterator
    snap = await it.__anext__()        # snapshot
    beat = await it.__anext__()        # silence + worker alive → heartbeat
    await q.put({"type": "done", "nodes": 1})
    done = await it.__anext__()        # a real event ends the stream
    rest = [c async for c in it]       # exhaust → break + finally(unsubscribe)

    assert "snapshot" in str(snap)
    assert "heartbeat" in str(beat)
    assert "done" in str(done)
    assert rest == [] and fj.unsubscribed


async def test_events_stale_when_worker_vanished(db, monkeypatch):
    import app.api.jobs_routes as jr
    monkeypatch.setattr(jr, "HEARTBEAT_S", 0.01)
    job = Job(id="orphan", params=JobParams(seed_id="10/x"), created_at="t")
    job.progress.status = JobStatus.expanding
    await db.create_job(job)

    fj = _Jobs(asyncio.Queue(), running=False)   # task gone, status still non-terminal
    resp = await job_events(job_id="orphan", jobs=fj, db=db)
    text = " ".join([str(c) async for c in resp.body_iterator])

    assert "snapshot" in text and "stale" in text
    assert fj.unsubscribed


async def test_events_end_when_job_finishes_between_events(monkeypatch):
    import app.api.jobs_routes as jr
    monkeypatch.setattr(jr, "HEARTBEAT_S", 0.01)
    # route-entry sees 'expanding' (so it streams); the in-loop re-check sees 'completed'
    seq = _SeqDB([JobStatus.expanding, JobStatus.completed])
    fj = _Jobs(asyncio.Queue(), running=False)
    resp = await job_events(job_id="fin", jobs=fj, db=seq)
    text = " ".join([str(c) async for c in resp.body_iterator])

    assert "snapshot" in text and "end" in text
    assert fj.unsubscribed
