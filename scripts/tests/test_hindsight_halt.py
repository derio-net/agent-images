"""halt-container helper (agent-images#170): stop the whole container with a code.

Writes the exit code to s6-overlay v3's container results file, then execs
s6's halt. Both paths are env seams so the test never touches /run.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE = REPO_ROOT / "hermes-agent-shell-hindsight"
HALT = IMAGE / "rootfs/usr/local/lib/hindsight/halt-container"
DOCKERFILE = IMAGE / "Dockerfile"


def _run(tmp_path, *args):
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    stub = tmp_path / "halt"
    calls = tmp_path / "calls"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
    stub.chmod(0o755)
    env = {**os.environ, "S6_RESULTS_DIR": str(results), "S6_HALT": str(stub)}
    p = subprocess.run(["bash", str(HALT), *args], env=env,
                       capture_output=True, text=True, timeout=30)
    return p, results, calls


def test_writes_exitcode_and_halts_once(tmp_path):
    p, results, calls = _run(tmp_path, "125", "why")
    assert p.returncode == 0
    assert (results / "exitcode").read_text().strip() == "125"
    assert len(calls.read_text().splitlines()) == 1
    assert "why" in p.stderr


def test_missing_code_is_usage_error(tmp_path):
    p, _, calls = _run(tmp_path)
    assert p.returncode == 2
    assert "usage" in p.stderr.lower()
    assert not calls.exists()


def test_every_new_script_is_chmodded_in_dockerfile():
    text = DOCKERFILE.read_text()
    for rel in ("usr/local/lib/hindsight/halt-container",
                "etc/cont-init.d/35-hindsight-port-preflight"):
        if (IMAGE / "rootfs" / rel).exists():
            assert f"/{rel}" in text, f"Dockerfile chmod +x list misses /{rel}"
