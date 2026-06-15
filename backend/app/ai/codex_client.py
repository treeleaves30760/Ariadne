"""Async wrapper around the OpenAI Codex CLI (`codex exec`) for structured output.

We invoke ``codex exec`` non-interactively with a JSON Schema (`--output-schema`)
and read the final message from a file (`-o`). Concurrency is bounded by a
semaphore and a per-client call counter enforces a global ceiling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import RuntimeConfig

log = logging.getLogger(__name__)


class CodexError(RuntimeError):
    pass


class CodexBudgetExceeded(CodexError):
    pass


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # remove ```json ... ``` fencing
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def _extract_json(text: str) -> Any:
    t = _strip_fences(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # fall back to the outermost {...} or [...] span
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = t.find(open_c)
            end = t.rfind(close_c)
            if start != -1 and end > start:
                try:
                    return json.loads(t[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise CodexError(f"could not parse JSON from codex output: {text[:300]!r}")


class CodexClient:
    def __init__(
        self,
        settings: Settings,
        *,
        max_calls: int | None = None,
        runtime: RuntimeConfig | None = None,
    ):
        self.settings = settings
        self.bin = shutil.which(settings.codex_bin) or settings.codex_bin
        rt = runtime or RuntimeConfig()
        self.model = rt.model or settings.codex_model
        self.reasoning_effort = rt.reasoning_effort
        self.api_base = rt.api_base
        self.api_key = rt.api_key
        self.timeout = settings.codex_timeout_s
        self._sem = asyncio.Semaphore(max(1, settings.codex_concurrency))
        self._calls = 0
        self._max_calls = max_calls if max_calls is not None else settings.max_codex_calls
        self._budget_lock = asyncio.Lock()  # atomic budget reservation for concurrent calls

    @property
    def calls(self) -> int:
        return self._calls

    def remaining(self) -> int:
        return max(0, self._max_calls - self._calls)

    async def run_structured(
        self, prompt: str, schema: dict[str, Any], *, model: str | None = None
    ) -> Any:
        """Run codex with an output JSON Schema; return the parsed JSON object."""
        # Reserve a budget slot atomically so concurrent callers can't overshoot the ceiling.
        async with self._budget_lock:
            if self._calls >= self._max_calls:
                raise CodexBudgetExceeded(
                    f"codex call budget exhausted ({self._max_calls})"
                )
            self._calls += 1
            call_no = self._calls

        tmpdir = Path(tempfile.mkdtemp(prefix="codex_"))
        schema_file = tmpdir / "schema.json"
        out_file = tmpdir / "out.json"
        schema_file.write_text(json.dumps(schema), encoding="utf-8")

        args = [self.bin, "exec", "--skip-git-repo-check"]
        if self.settings.codex_bypass_sandbox:
            # The container is the isolation boundary; Codex's Landlock/seccomp
            # sandbox can't initialize inside Docker, so bypass it there.
            args.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            args += ["-s", "read-only"]
        args += [
            "--ephemeral",
            "--color",
            "never",
            "--output-schema",
            str(schema_file),
            "-o",
            str(out_file),
        ]
        chosen_model = model or self.model
        if chosen_model:
            args += ["-m", chosen_model]
        if self.reasoning_effort:
            args += ["-c", f'model_reasoning_effort="{self.reasoning_effort}"']
        if self.api_base:
            args += ["-c", f'model_providers.openai.base_url="{self.api_base}"',
                     "-c", 'model_provider="openai"']
        if self.api_key:
            args += ["-c", 'preferred_auth_method="apikey"']
        args.append("-")  # read prompt from stdin

        env = os.environ.copy()
        if self.api_key:
            env["OPENAI_API_KEY"] = self.api_key
        if self.api_base:
            env["OPENAI_BASE_URL"] = self.api_base

        def _run() -> subprocess.CompletedProcess[bytes]:
            # Synchronous subprocess in a worker thread, on purpose: it works no
            # matter which asyncio event loop is running. On Windows the asyncio
            # SelectorEventLoop cannot create subprocesses (it raises a bare
            # NotImplementedError), and servers like uvicorn may install it — so we
            # never spawn from the loop itself. Passing `input=` closes stdin (EOF)
            # so `codex exec` won't hang waiting for more input.
            return subprocess.run(
                args,
                input=prompt.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=self.timeout,
            )

        async with self._sem:
            log.info("codex call #%d/%d starting (model=%s)",
                     call_no, self._max_calls, chosen_model or "default")
            t0 = time.monotonic()
            try:
                try:
                    proc = await asyncio.to_thread(_run)
                except subprocess.TimeoutExpired as exc:
                    log.warning("codex call #%d timed out after %.0fs", call_no, self.timeout)
                    raise CodexError(f"codex timed out after {self.timeout}s") from exc

                dt = time.monotonic() - t0
                if proc.returncode != 0:
                    log.warning("codex call #%d failed rc=%d in %.1fs",
                                call_no, proc.returncode, dt)
                    raise CodexError(
                        f"codex exited {proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[:500]}"
                    )
                log.info("codex call #%d done in %.1fs", call_no, dt)

                if out_file.exists():
                    raw = out_file.read_text(encoding="utf-8").strip()
                    if raw:
                        return _extract_json(raw)
                # fall back to stdout if the output file was empty
                return _extract_json(proc.stdout.decode("utf-8", "replace"))
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
