"""Tests for guardrails-hook.py — PostToolUse audit write path."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).parent.parent / "scripts" / "guardrails-hook.py"


def _run_hook(payload: dict, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


def test_posttooluse_bash_writes_audit_line(tmp_path):
    fake_home = tmp_path
    (fake_home / ".willikins-agent").mkdir(parents=True, exist_ok=True)
    expected_log = fake_home / ".willikins-agent" / "audit.jsonl"

    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
        "tool_response": {"exit_code": 0},
        "session_id": "test-session-42",
    }

    result = _run_hook(payload, {"HOME": str(fake_home)})
    assert result.returncode == 0, f"hook exited non-zero: {result.stderr}"

    assert expected_log.exists(), (
        f"audit.jsonl was not created at {expected_log}. "
        f"hook stderr: {result.stderr}"
    )
    lines = expected_log.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["command"] == "ls -la"
    assert entry["exit_code"] == 0
    assert entry["session"] == "test-session-42"


def test_posttooluse_non_bash_no_write(tmp_path):
    fake_home = tmp_path
    (fake_home / ".willikins-agent").mkdir(parents=True, exist_ok=True)
    expected_log = fake_home / ".willikins-agent" / "audit.jsonl"

    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/passwd"},
        "tool_response": {},
        "session_id": "t",
    }
    result = _run_hook(payload, {"HOME": str(fake_home)})
    assert result.returncode == 0
    assert not expected_log.exists()
