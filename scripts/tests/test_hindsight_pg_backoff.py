"""Guard: the hindsight postgres longrun backs off and gives up (agent-images#160).

The `postgres` s6 longrun in hermes-agent-shell-hindsight used to ship only a
`run` script. With no `finish`, s6-supervise's policy is "restart after one
second, forever" - so a fatal, non-transient startup failure (postgres could
not bind 127.0.0.1:5433 because something else in the shared pod netns held
it) became a 1 Hz fork storm. Each attempt is a real postmaster that maps
shared buffers before discovering it cannot listen; on frank that walked the
container into its 2Gi limit 22 times.

The contract these tests pin:

* `finish` counts FAST failures (died within the fast window of starting) and,
  after a bounded number of them, exits 125 - s6's "permanent failure, do not
  restart" code.
* Between fast failures, the next `run` sleeps a growing delay before it execs
  postgres. The sleep lives in `run`, not `finish`: s6 kills a `finish` after
  5s (no `timeout-finish` here), and a sleeping `run` stays stoppable by
  `s6-svc -d`.
* A clean stop (exit 0, or SIGTERM/SIGINT/SIGQUIT from s6 or shutdown) is not
  a failure, and a crash after a long healthy uptime starts the count afresh.

The scripts are executed for real with bash, in a temp dir standing in for the
s6 service directory (s6 runs both with cwd = the service dir), with `sleep`
and `micromamba` stubbed on PATH.
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE = REPO_ROOT / "hermes-agent-shell-hindsight"
SERVICE = IMAGE / "rootfs/etc/services.d/postgres"
RUN = SERVICE / "run"
FINISH = SERVICE / "finish"
DOCKERFILE = IMAGE / "Dockerfile"

# Upper bound on how many fast failures may happen before the service gives
# up. The point of #160 is "bounded", so the test caps it rather than pinning
# the exact tuning.
MAX_ATTEMPTS = 6


@pytest.fixture
def svc(tmp_path):
    """A fake service dir plus a PATH whose sleep/micromamba are recorders."""
    svcdir = tmp_path / "svc"
    svcdir.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    sleeps = tmp_path / "sleeps.log"
    (bindir / "sleep").write_text(f'#!/bin/sh\necho "$1" >> "{sleeps}"\n')
    # postgres failing to bind: exits 1 immediately.
    (bindir / "micromamba").write_text("#!/bin/sh\nexit 1\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}

    class Svc:
        dir = svcdir

        def run(self):
            return subprocess.run(["bash", str(RUN)], cwd=svcdir, env=env,
                                  capture_output=True, text=True, timeout=30)

        def finish(self, code, sig=0):
            return subprocess.run(["bash", str(FINISH), str(code), str(sig)],
                                  cwd=svcdir, env=env, capture_output=True,
                                  text=True, timeout=30)

        def sleeps(self):
            if not sleeps.exists():
                return []
            return [int(x) for x in sleeps.read_text().split()]

    return Svc()


def _crash_loop(svc, limit=50):
    """Drive run -> finish(1) the way s6 would, until finish says stop."""
    for attempt in range(1, limit + 1):
        svc.run()
        rc = svc.finish(1).returncode
        if rc == 125:
            return attempt
        assert rc == 0, f"finish must exit 0 (restart) or 125 (give up), got {rc}"
    return None


def test_finish_exists_and_is_built_executable():
    assert FINISH.exists(), "postgres longrun needs a finish script (#160)"
    assert FINISH.read_text().startswith("#!/command/with-contenv bash")
    assert "/etc/services.d/postgres/finish" in DOCKERFILE.read_text(), (
        "Dockerfile must chmod +x the finish script - the agent UID cannot "
        "chmod root-owned files at runtime"
    )


def test_fatal_startup_failure_gives_up(svc):
    attempts = _crash_loop(svc)
    assert attempts is not None, "finish never exited 125: s6 would restart forever"
    assert attempts <= MAX_ATTEMPTS


def test_restarts_back_off(svc):
    _crash_loop(svc)
    delays = svc.sleeps()
    assert delays, "run never backed off before re-execing postgres"
    assert delays == sorted(delays), f"backoff must not shrink: {delays}"
    assert delays[-1] > delays[0], f"backoff must grow: {delays}"
    assert max(delays) <= 60


def test_first_start_does_not_sleep(svc):
    svc.run()
    assert svc.sleeps() == []


@pytest.mark.parametrize("code,sig", [(0, 0), (256, 15), (256, 2), (256, 3)])
def test_clean_stop_is_not_a_failure(svc, code, sig):
    for _ in range(MAX_ATTEMPTS + 2):
        svc.run()
        assert svc.finish(code, sig).returncode == 0
    assert svc.sleeps() == []


def test_crash_after_long_uptime_resets_the_count(svc):
    # State file format (documented in finish): "<fast_failures> <next_delay>
    # <started_epoch>". Seed a count one short of any sane limit, with a
    # postgres that had been up for an hour when it crashed.
    (svc.dir / "backoff").write_text(f"{MAX_ATTEMPTS * 10} 60 {int(time.time()) - 3600}\n")
    assert svc.finish(1).returncode == 0
    # The count genuinely restarted: a full bounded run is still available.
    assert _crash_loop(svc) > 1
