"""Phase 1 / F3 — Kali container smoke test for the v2.2.0 bridge.

Opt-in: set ``KALI_IMAGE`` to a built image tag (e.g. ``secure-agent-kali:dev``)
to run this against a local build. CI runs the same docker-exec assertions
directly in ``smoke-test-secure-agent-kali`` against the freshly-built image,
so this file exists primarily for on-demand local verification.
"""
from __future__ import annotations

import os
import subprocess

import pytest

IMAGE = os.environ.get("KALI_IMAGE")


@pytest.mark.smoke
@pytest.mark.skipif(
    not IMAGE,
    reason="KALI_IMAGE not set — point at a built kali image to run this smoke",
)
def test_bridge_wrapper_dry_run():
    """
    GIVEN a built kali image
    WHEN  invoking ``docker run --rm $KALI_IMAGE /opt/vk-bridge/run.sh --dry-run``
    THEN  the process exits 0
    AND   stdout's first line is the version banner ``[bridge] - v2.2.0 - …``
    AND   stdout contains ``vk.bridge: dry-run complete``
    """
    result = subprocess.run(
        ["docker", "run", "--rm", IMAGE, "/opt/vk-bridge/run.sh", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "vk.bridge: dry-run complete" in result.stdout
    first_line = result.stdout.splitlines()[0]
    assert first_line.startswith("[bridge] - v2.2.0 - "), first_line
