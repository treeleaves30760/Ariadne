"""Tests for JobManager: run lifecycle, emit-event handling, and pub/sub."""

from __future__ import annotations

import asyncio

import app.jobs.manager as manager_mod
from app.config import Settings
from app.jobs.manager import JobManager
from app.models import ExternalIds, JobParams, JobStatus, Paper

SEED = Paper(id="10/seed", title="Seed", external_ids=ExternalIds(doi="10/seed"))


class FakeLibrary:
    async def get_paper(self, canonical, ext=None):
        return None


class FakeExpander:
    """Stand-in for GraphExpander that drives the manager's emit closure."""

    script: list[dict] = []

    def __init__(self, job_id, seed, params, *, library, codex, db, settings, emit=None):
        self._emit = emit

    async def run(self):
        for ev in FakeExpander.script:
            await self._emit(ev)


class BoomExpander:
    def __init__(self, *a, **k):
        pass

    async def run(self):
        raise RuntimeError("boom")


async def _manager(db):
    return JobManager(db, FakeLibrary(), Settings(max_codex_calls=200))


async def test_run_success_updates_progress_and_publishes(db, monkeypatch):
    monkeypatch.setattr(manager_mod, "GraphExpander", FakeExpander)
    FakeExpander.script = [
        {"type": "progress", "level": 1, "nodes": 3, "edges": 2, "codex_calls": 1, "message": "m",
         "phase": "score", "elapsed_s": 4.5, "timings": {"fetch": 1.0, "score": 3.5}},
        {"type": "activity", "message": "feed only"},
        {"type": "note", "message": "a note"},
        {"type": "reporting", "level": "final", "message": "reporting"},
        {"type": "report_ready", "level": "3"},
        {"type": "report_ready", "level": "3"},  # duplicate ignored
    ]
    mgr = await _manager(db)
    await db.upsert_paper(SEED)
    job = await mgr.create_job(JobParams(seed_id="10/seed", depth=1))
    q = mgr.subscribe(job.id)
    await mgr._run(job.id)

    got = await db.get_job(job.id)
    assert got.progress.status == JobStatus.completed
    assert got.progress.nodes == 3
    assert got.progress.edges == 2
    assert got.progress.current_level == 1
    assert got.progress.phase == "score"
    assert got.progress.elapsed_s == 4.5
    assert got.progress.timings == {"fetch": 1.0, "score": 3.5}
    assert "a note" in got.progress.notes
    assert got.progress.reports_available == ["3"]

    types = []
    while not q.empty():
        types.append((await q.get()).get("type"))
    assert {"progress", "activity", "done"} <= set(types)


async def test_run_missing_job_is_noop(db, monkeypatch):
    monkeypatch.setattr(manager_mod, "GraphExpander", FakeExpander)
    FakeExpander.script = []
    mgr = await _manager(db)
    await mgr._run("does-not-exist")  # returns early, no raise


async def test_run_failure_marks_failed(db, monkeypatch):
    monkeypatch.setattr(manager_mod, "GraphExpander", BoomExpander)
    mgr = await _manager(db)
    await db.upsert_paper(SEED)
    job = await mgr.create_job(JobParams(seed_id="10/seed"))
    q = mgr.subscribe(job.id)
    await mgr._run(job.id)

    got = await db.get_job(job.id)
    assert got.progress.status == JobStatus.failed
    assert "boom" in got.error
    evs = []
    while not q.empty():
        evs.append(await q.get())
    assert any(e.get("type") == "failed" for e in evs)


async def test_run_unresolvable_seed_fails(db, monkeypatch):
    monkeypatch.setattr(manager_mod, "GraphExpander", FakeExpander)
    FakeExpander.script = []
    mgr = await _manager(db)
    job = await mgr.create_job(JobParams(seed_id="10/missing"))
    await mgr._run(job.id)
    got = await db.get_job(job.id)
    assert got.progress.status == JobStatus.failed
    assert "could not resolve seed" in got.error


async def test_subscribe_unsubscribe(db):
    mgr = await _manager(db)
    q = mgr.subscribe("j")
    assert "j" in mgr._subs
    mgr.unsubscribe("j", q)
    assert "j" not in mgr._subs   # last subscriber removed -> key dropped
    mgr.unsubscribe("j", q)       # idempotent


async def test_start_job_runs_in_background(db, monkeypatch):
    monkeypatch.setattr(manager_mod, "GraphExpander", FakeExpander)
    FakeExpander.script = []
    mgr = await _manager(db)
    await db.upsert_paper(SEED)
    job = await mgr.create_job(JobParams(seed_id="10/seed"))
    mgr.start_job(job.id)
    for _ in range(100):
        if job.id not in mgr._tasks:
            break
        await asyncio.sleep(0.01)
    got = await db.get_job(job.id)
    assert got.progress.status == JobStatus.completed


async def test_is_running_reflects_task_lifecycle(db, monkeypatch):
    monkeypatch.setattr(manager_mod, "GraphExpander", FakeExpander)
    FakeExpander.script = []
    mgr = await _manager(db)
    assert mgr.is_running("nope") is False           # never started → no task
    await db.upsert_paper(SEED)
    job = await mgr.create_job(JobParams(seed_id="10/seed"))
    mgr.start_job(job.id)
    assert mgr.is_running(job.id) is True             # task registered and still live
    for _ in range(100):
        if job.id not in mgr._tasks:
            break
        await asyncio.sleep(0.01)
    assert mgr.is_running(job.id) is False            # finished → popped from _tasks
