"""Tests for wrap-claude.py supervisor: envs file lifecycle."""
from __future__ import annotations
import json
import os
import signal
import subprocess
import time
from pathlib import Path

WRAP = Path(__file__).parent.parent / "scripts" / "wrap-claude.py"


def _fake_claude(tmp_path: Path, *, fd: str = "2") -> Path:
    """Write a fake claude that prints an env_id banner then sleeps.

    `fd` selects the stream the banner is emitted on: "1" (stdout) matches
    the real `claude remote-control` TUI banner, "2" (stderr) preserves the
    original spike-era assumption.
    """
    path = tmp_path / "fake-claude"
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"echo 'registered environment env_01TEST456789ABCDEFGH0' >&{fd}\n"
        "trap 'exit 0' TERM\n"
        "sleep 300 &\n"
        "wait $!\n"
    )
    path.chmod(0o755)
    return path


def test_graceful_sigterm_clears_envs_file(tmp_path):
    agent_dir = tmp_path / ".willikins-agent"
    envs_dir = agent_dir / "envs"
    envs_dir.mkdir(parents=True)

    fake = _fake_claude(tmp_path)
    env = {
        **os.environ,
        "WILLIKINS_AGENT_DIR": str(agent_dir),
        "CLAUDE_BIN_OVERRIDE": str(fake),
    }
    proc = subprocess.Popen(
        ["python3", "-u", str(WRAP), "willikins-test"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    target = envs_dir / "willikins-test.json"
    for _ in range(40):
        if target.exists():
            break
        time.sleep(0.1)
    assert target.exists(), f"envs file not created: {list(envs_dir.iterdir())}"
    data = json.loads(target.read_text())
    assert data["env_id"] == "env_01TEST456789ABCDEFGH0"
    assert data["pid"] > 0

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    assert proc.returncode == 0
    assert not target.exists(), "envs file should be removed on graceful exit"


def test_sigkill_leaves_envs_file(tmp_path):
    agent_dir = tmp_path / ".willikins-agent"
    envs_dir = agent_dir / "envs"
    envs_dir.mkdir(parents=True)

    fake = _fake_claude(tmp_path)
    env = {
        **os.environ,
        "WILLIKINS_AGENT_DIR": str(agent_dir),
        "CLAUDE_BIN_OVERRIDE": str(fake),
    }
    proc = subprocess.Popen(
        ["python3", "-u", str(WRAP), "willikins-test"],
        env=env,
    )
    target = envs_dir / "willikins-test.json"
    for _ in range(40):
        if target.exists():
            break
        time.sleep(0.1)
    assert target.exists()

    # Capture the child PID for post-SIGKILL liveness check below. We can
    # read it from the envs file because the wrapper writes child.pid there.
    child_pid = json.loads(target.read_text())["pid"]

    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=5)
    # SIGKILL on the wrapper does not run the unlink path; the file is left
    # behind for the reaper to find.
    assert target.exists(), "envs file should persist on SIGKILL"

    # PDEATHSIG: when the wrapper dies the kernel sends SIGTERM to the
    # child. fake-claude's TERM trap exits cleanly. Verify within a short
    # window that the child does not outlive the wrapper — that's the
    # whole point of pdeathsig vs. the previous test's pkill cleanup hack.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        # Best-effort cleanup so pytest still exits if pdeathsig didn't fire
        # (e.g. running under a non-Linux kernel where _set_pdeathsig is a
        # no-op).
        try:
            os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise AssertionError(
            f"child {child_pid} survived wrapper SIGKILL — pdeathsig did not fire"
        )


def test_env_id_on_stdout_is_captured(tmp_path):
    """Real `claude remote-control` prints the env_id banner on stdout, not
    stderr (the spike-era assumption baked into the original wrapper). This
    test pins the fix in place — if the wrapper regresses to stderr-only
    scraping, production envs/<session>.json files will silently stay empty
    and the reaper will be a no-op, exactly as observed on c804fab."""
    agent_dir = tmp_path / ".willikins-agent"
    envs_dir = agent_dir / "envs"
    envs_dir.mkdir(parents=True)

    fake = _fake_claude(tmp_path, fd="1")  # stdout
    env = {
        **os.environ,
        "WILLIKINS_AGENT_DIR": str(agent_dir),
        "CLAUDE_BIN_OVERRIDE": str(fake),
    }
    proc = subprocess.Popen(
        ["python3", "-u", str(WRAP), "willikins-test"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    target = envs_dir / "willikins-test.json"
    try:
        for _ in range(40):
            if target.exists():
                break
            time.sleep(0.1)
        assert target.exists(), (
            "envs file not created — wrapper failed to scrape env_id from stdout"
        )
        assert json.loads(target.read_text())["env_id"] == "env_01TEST456789ABCDEFGH0"
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
