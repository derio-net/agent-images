"""Port pre-flight cont-init (agent-images#170): refuse to boot if 5433 is held."""
import os

import pytest
import socket
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (REPO_ROOT / "hermes-agent-shell-hindsight"
          / "rootfs/etc/cont-init.d/35-hindsight-port-preflight")


def _run(port, path_prefix=None):
    env = {**os.environ, "HINDSIGHT_PG_PORT": str(port)}
    if path_prefix:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    return subprocess.run(["bash", str(SCRIPT)], env=env,
                          capture_output=True, text=True, timeout=30)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_held_port_fails_loudly():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        p = _run(port)
    assert p.returncode == 1
    assert f"127.0.0.1:{port}" in p.stderr
    assert "already in use" in p.stderr


def test_free_port_passes():
    assert _run(_free_port()).returncode == 0


@pytest.mark.parametrize("rc", [124, 127])
def test_probe_error_fails_closed(tmp_path, rc):
    # 124 = no answer within the bound, 127 = the probe could not run: neither
    # proves the port free, so boot must stop and say why (tests-lens l-tests-r3).
    stub = tmp_path / "timeout"
    stub.write_text(f"#!/bin/sh\nexit {rc}\n")
    stub.chmod(0o755)
    p = _run(_free_port(), path_prefix=tmp_path)
    assert p.returncode == 1
    assert f"probe rc={rc}" in p.stderr
