"""F3 — Kali container smoke test for the rebuilt vk.bridge.

Runs `python -m vk.bridge --dry-run` inside the built kali image and
verifies the bridge starts, prints the v2.2.0 version banner, and exits
cleanly. Marker-gated (`smoke`) so it only runs against a freshly-built
image; the default `pytest tests/` invocation in CI skips it.

Image to test is taken from the `KALI_IMAGE` env var (set by the CI
workflow to the SHA-tagged tag pushed by `build-children`). Falls back
to a local dev tag for ad-hoc runs.
"""
from __future__ import annotations

import os
import subprocess

import pytest


KALI_IMAGE = os.environ.get("KALI_IMAGE", "agent-images-kali:dev")
VK_VERSION = "v2.2.0"


@pytest.mark.smoke
def test_python_m_vk_bridge_dry_run_in_container():
    """`docker run <kali> python -m vk.bridge --dry-run` must exit 0 with banner."""
    result = subprocess.run(
        [
            "docker", "run", "--rm", KALI_IMAGE,
            "/opt/vk-bridge-venv/bin/python", "-m", "vk.bridge", "--dry-run",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "vk.bridge: dry-run complete" in result.stdout, result.stdout
    first_line = result.stdout.splitlines()[0]
    assert first_line.startswith(f"[bridge] - {VK_VERSION} - "), first_line


@pytest.mark.smoke
def test_bridge_wrapper_runs_in_container():
    """The /opt/vk-bridge/run.sh wrapper (what cron invokes) must also work."""
    result = subprocess.run(
        ["docker", "run", "--rm", KALI_IMAGE, "/opt/vk-bridge/run.sh", "--dry-run"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "vk.bridge: dry-run complete" in result.stdout, result.stdout
