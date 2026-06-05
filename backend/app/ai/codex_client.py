"""Async wrapper around the OpenAI Codex CLI (`codex exec`) for structured output.

We invoke ``codex exec`` non-interactively with a JSON Schema (`--output-schema`)
and read the final message from a file (`-o`). Concurrency is bounded by a
semaphore and a per-client call counter enforces a global ceiling.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models import RuntimeConfig


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

    @property
    def calls(self) -> int:
        return self._calls

    def remaining(self) -> int:
        return max(0, self._max_calls - self._calls)

    async def run_structured(
        self, prompt: str, schema: dict[str, Any], *, model: str | None = None
    ) -> Any:
        """Run codex with an output JSON Schema; return the parsed JSON object."""
        if self._calls >= self._max_calls:
            raise CodexBudgetExceeded(
                f"codex call budget exhausted ({self._max_calls})"
            )

        tmpdir = Path(tempfile.mkdtemp(prefix="codex_"))
        schema_file = tmpdir / "schema.json"
        out_file = tmpdir / "out.json"
        schema_file.write_text(json.dumps(schema), encoding="utf-8")

        args = [
            self.bin,
            "exec",
            "--skip-git-repo-check",
            "-s",
            "read-only",
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

        async with self._sem:
            self._calls += 1
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(prompt.encode("utf-8")), timeout=self.timeout
                    )
                except asyncio.TimeoutError as exc:
                    proc.kill()
                    await proc.wait()
                    raise CodexError(f"codex timed out after {self.timeout}s") from exc

                if proc.returncode != 0:
                    raise CodexError(
                        f"codex exited {proc.returncode}: {stderr.decode('utf-8', 'replace')[:500]}"
                    )

                if out_file.exists():
                    raw = out_file.read_text(encoding="utf-8").strip()
                    if raw:
                        return _extract_json(raw)
                # fall back to stdout if the output file was empty
                return _extract_json(stdout.decode("utf-8", "replace"))
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
