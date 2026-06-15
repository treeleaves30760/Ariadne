"""JobManager: creates, runs, and streams progress for expansion jobs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.ai.codex_client import CodexClient
from app.config import Settings
from app.graph.expander import GraphExpander
from app.models import Job, JobParams, JobProgress, JobStatus
from app.services.library import PaperLibrary
from app.storage.db import Database

log = logging.getLogger(__name__)

TERMINAL = {JobStatus.completed, JobStatus.failed}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, db: Database, library: PaperLibrary, settings: Settings):
        self.db = db
        self.library = library
        self.settings = settings
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------ pub/sub ------------------------------ #
    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(job_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(job_id, None)

    async def _publish(self, job_id: str, event: dict) -> None:
        for q in list(self._subs.get(job_id, ())):
            await q.put(event)

    # ------------------------------- jobs -------------------------------- #
    async def create_job(self, params: JobParams) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], params=params, progress=JobProgress(),
                  created_at=_now())
        await self.db.create_job(job)
        return job

    def start_job(self, job_id: str) -> None:
        task = asyncio.create_task(self._run(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda t: self._tasks.pop(job_id, None))

    def is_running(self, job_id: str) -> bool:
        """True while the background task for this job is still executing.

        Lets the SSE stream tell "still generating" (quiet but alive) apart from
        "the worker is gone" (e.g. a process restart) during long event gaps.
        """
        task = self._tasks.get(job_id)
        return task is not None and not task.done()

    async def _run(self, job_id: str) -> None:
        job = await self.db.get_job(job_id)
        if not job:
            return
        rt = await self.db.get_runtime_config()
        codex = CodexClient(self.settings, max_calls=self.settings.max_codex_calls, runtime=rt)

        async def emit(event: dict) -> None:
            p = job.progress
            t = event.get("type")
            if t == "activity":
                # high-frequency, ephemeral feed events: publish only, no DB write
                await self._publish(job_id, event)
                return
            if isinstance(event.get("level"), int):  # report levels are strings; skip those
                p.current_level = event["level"]
            if "nodes" in event:
                p.nodes = event["nodes"]
            if event.get("edges"):
                p.edges += event["edges"]
            if "codex_calls" in event:
                p.codex_calls = event["codex_calls"]
            if event.get("phase"):
                p.phase = event["phase"]
            if "elapsed_s" in event:
                p.elapsed_s = event["elapsed_s"]
            if event.get("timings"):
                p.timings = event["timings"]
            if event.get("message"):
                p.message = event["message"]
            if t == "note" and event.get("message"):
                p.notes.append(event["message"])
            if t == "reporting":
                p.status = JobStatus.reporting
            elif t in ("progress", "note"):
                p.status = JobStatus.expanding
            if t == "report_ready":
                lvl = event["level"]
                if lvl not in p.reports_available:
                    p.reports_available.append(lvl)
            await self.db.update_job(job)
            # Surface the live status to subscribers so the UI pill tracks reality
            # (progress/reporting events otherwise wouldn't carry the updated status).
            await self._publish(job_id, {**event, "status": p.status})

        try:
            job.progress.status = JobStatus.resolving
            job.progress.message = "resolving seed paper"
            await self.db.update_job(job)
            await self._publish(job_id, {"type": "progress", "message": "resolving seed paper"})

            seed = await self.db.get_paper(job.params.seed_id) or await self.library.get_paper(
                job.params.seed_id
            )
            if not seed:
                raise ValueError(f"could not resolve seed paper: {job.params.seed_id}")
            log.info("job %s: seed resolved → %r; expanding to depth %d",
                     job_id, seed.title[:60], job.params.depth)

            expander = GraphExpander(
                job_id, seed, job.params,
                library=self.library, codex=codex, db=self.db,
                settings=self.settings, emit=emit,
            )
            await expander.run()

            job.progress.status = JobStatus.completed
            job.progress.message = "completed"
            await self.db.update_job(job)
            log.info("job %s: completed — %d nodes, %d Codex calls, %.0fs",
                     job_id, job.progress.nodes, codex.calls, job.progress.elapsed_s)
            await self._publish(job_id, {"type": "done", "nodes": job.progress.nodes,
                                         "codex_calls": codex.calls})
        except Exception as exc:  # noqa: BLE001
            job.error = f"{type(exc).__name__}: {exc}"
            job.progress.status = JobStatus.failed
            job.progress.message = job.error
            log.warning("job %s: failed — %s", job_id, job.error)
            await self.db.update_job(job)
            await self._publish(job_id, {"type": "failed", "error": job.error})
