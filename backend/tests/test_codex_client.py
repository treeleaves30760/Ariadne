"""Tests for CodexClient flag/env assembly and subprocess error handling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.ai.codex_client import CodexClient, CodexError, _extract_json
from app.config import Settings
from app.models import RuntimeConfig


def test_extract_json_unparseable_raises():
    # Has a brace span that still fails to parse -> exercises the inner continue + final raise.
    with pytest.raises(CodexError):
        _extract_json("prefix {bad json} suffix")


def _capture(monkeypatch, *, payload=None, returncode=0, write_out=True, raise_timeout=False):
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env", {})
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd=args, timeout=1)
        if write_out and payload is not None:
            Path(args[args.index("-o") + 1]).write_text(json.dumps(payload), encoding="utf-8")
        stdout = b"" if write_out else json.dumps(payload).encode()
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=b"boom-stderr")

    monkeypatch.setattr("app.ai.codex_client.subprocess.run", fake_run)
    return captured


async def test_runtime_flags_and_env_are_passed(monkeypatch):
    cap = _capture(monkeypatch, payload={"ok": 1})
    rt = RuntimeConfig(model="gpt-5.5", reasoning_effort="high",
                       api_base="https://api.example.com/v1", api_key="sk-123")
    codex = CodexClient(Settings(), runtime=rt)
    assert await codex.run_structured("hi", {"type": "object"}) == {"ok": 1}
    args = cap["args"]
    assert "-m" in args and "gpt-5.5" in args
    assert any("model_reasoning_effort" in a for a in args)
    assert any("base_url" in a for a in args)
    assert 'preferred_auth_method="apikey"' in args
    assert cap["env"]["OPENAI_API_KEY"] == "sk-123"
    assert cap["env"]["OPENAI_BASE_URL"] == "https://api.example.com/v1"


async def test_model_override_argument(monkeypatch):
    cap = _capture(monkeypatch, payload={"ok": 1})
    codex = CodexClient(Settings())
    await codex.run_structured("hi", {"type": "object"}, model="gpt-5.4")
    assert "gpt-5.4" in cap["args"]


async def test_timeout_raises_codex_error(monkeypatch):
    _capture(monkeypatch, raise_timeout=True)
    codex = CodexClient(Settings())
    with pytest.raises(CodexError, match="timed out"):
        await codex.run_structured("hi", {"type": "object"})


async def test_nonzero_returncode_raises_with_stderr(monkeypatch):
    _capture(monkeypatch, payload={}, returncode=2, write_out=False)
    codex = CodexClient(Settings())
    with pytest.raises(CodexError, match="codex exited 2"):
        await codex.run_structured("hi", {"type": "object"})


async def test_falls_back_to_stdout_when_no_output_file(monkeypatch):
    _capture(monkeypatch, payload={"from": "stdout"}, write_out=False)
    codex = CodexClient(Settings())
    assert await codex.run_structured("hi", {"type": "object"}) == {"from": "stdout"}


async def test_bypass_sandbox_uses_danger_flag(monkeypatch):
    cap = _capture(monkeypatch, payload={"ok": 1})
    codex = CodexClient(Settings(codex_bypass_sandbox=True))
    await codex.run_structured("hi", {"type": "object"})
    assert "--dangerously-bypass-approvals-and-sandbox" in cap["args"]
    assert "read-only" not in cap["args"]


async def test_default_uses_read_only_sandbox(monkeypatch):
    cap = _capture(monkeypatch, payload={"ok": 1})
    codex = CodexClient(Settings())  # bypass off by default
    await codex.run_structured("hi", {"type": "object"})
    assert "-s" in cap["args"] and "read-only" in cap["args"]
    assert "--dangerously-bypass-approvals-and-sandbox" not in cap["args"]
