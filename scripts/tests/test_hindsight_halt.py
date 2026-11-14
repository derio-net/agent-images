"""halt-container helper (agent-images#170): stop the whole container with a code.

Writes the exit code to s6-overlay v3's container results file, then execs
s6's halt. Both paths are env seams so the test never touches /run.
"""
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE = REPO_ROOT / "hermes-agent-shell-hindsight"
HALT = IMAGE / "rootfs/usr/local/lib/hindsight/halt-container"
DOCKERFILE = IMAGE / "Dockerfile"


def _run(tmp_path, *args, make_results=True, halt=None):
    results = tmp_path / "results"
    if make_results:
        results.mkdir(exist_ok=True)
    stub = tmp_path / "halt"
    calls = tmp_path / "calls"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
    stub.chmod(0o755)
    env = {**os.environ, "S6_RESULTS_DIR": str(results),
           "S6_HALT": str(halt if halt is not None else stub)}
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
    # The scripts must exist AND sit inside the Dockerfile's `chmod +x` list —
    # not merely be mentioned somewhere (e.g. a comment).
    text = DOCKERFILE.read_text()
    m = re.search(r"chmod \+x \\\n((?:[ \t]+\S+[ \t]*\\?\n)+)", text)
    assert m, "Dockerfile has no multi-line `chmod +x` list"
    listed = {line.strip().rstrip("\\").strip() for line in m.group(1).splitlines()}
    for rel in ("usr/local/lib/hindsight/halt-container",
                "etc/cont-init.d/35-hindsight-port-preflight",
                "etc/services.d/postgres/finish",
                "etc/services.d/hindsight-api/run"):
        assert (IMAGE / "rootfs" / rel).is_file(), f"missing rootfs/{rel}"
        assert f"/{rel}" in listed, f"Dockerfile chmod +x list misses /{rel}"

def test_multi_word_reason_is_printed_whole(tmp_path):
    # finish wraps its reason across two arguments; none of it may be dropped.
    p, _, _ = _run(tmp_path, "125", "postgres gave up;", "check the log above (port 5433)")
    assert "postgres gave up; check the log above (port 5433)" in p.stderr


def test_unwritable_exitcode_is_loud_but_still_halts(tmp_path):
    p, _, calls = _run(tmp_path, "125", "why", make_results=False)
    assert "FATAL: could not write exit code 125" in p.stderr
    assert len(calls.read_text().splitlines()) == 1


def test_unexecable_halt_is_loud_and_returns_111(tmp_path):
    p, results, _ = _run(tmp_path, "125", "why", halt=tmp_path / "no-such-halt")
    assert p.returncode == 111
    assert "FATAL: could not exec" in p.stderr
    assert (results / "exitcode").read_text().strip() == "125"
