"""Port pre-flight cont-init (agent-images#170): refuse to boot if 5433 is held."""
import os
import socket
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (REPO_ROOT / "hermes-agent-shell-hindsight"
          / "rootfs/etc/cont-init.d/35-hindsight-port-preflight")


def _run(port):
    env = {**os.environ, "HINDSIGHT_PG_PORT": str(port)}
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
