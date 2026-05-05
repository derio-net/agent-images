#!/usr/bin/env python3
"""wrap-claude.py — supervisor around `claude remote-control` that records the
bridge env_id to a file we own, so an orphan reaper can clean up when claude
dies without invoking its own bridge:shutdown handler.

Usage:
  wrap-claude.py <session_name> [extra claude args...]

Environment:
  WILLIKINS_AGENT_DIR  — default ~/.willikins-agent (envs file lives here)
  CLAUDE_BIN_OVERRIDE  — alternate binary path, for tests
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# env IDs observed in the wild are 24+ chars of [A-Za-z0-9] (e.g.
# env_01MPTBz8CJR82vP2qXJKpUvt — see Phase 0 findings). Tighten the regex to
# match that shape rather than the looser `env_[A-Za-z0-9_-]{6,}` template,
# which would false-positive on stray `env_foo` substrings in unrelated logs.
ENV_RE = re.compile(r"env_[A-Za-z0-9]{20,}")

# PR_SET_PDEATHSIG: when the wrapper process dies (including via SIGKILL),
# the kernel delivers this signal to the child. Closes the orphan-on-
# wrapper-SIGKILL hole — without it, shutdown.sh's grace-window SIGKILL
# would leave claude reparented to PID 1.
_PR_SET_PDEATHSIG = 1


def _set_pdeathsig() -> None:
    """preexec_fn — runs in the child between fork and program-image swap."""
    if platform.system() != "Linux":
        return
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
    except OSError:
        return
    # Send SIGTERM to the child if the parent dies. claude's own SIGTERM
    # handler still runs bridge:shutdown if it's responsive; if it isn't,
    # the container teardown takes it the rest of the way.
    libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: wrap-claude.py <session_name> [extra args]", file=sys.stderr)
        return 2
    session = sys.argv[1]
    extra = sys.argv[2:]
    agent_dir = Path(os.environ.get("WILLIKINS_AGENT_DIR", Path.home() / ".willikins-agent"))
    envs_dir = agent_dir / "envs"
    envs_dir.mkdir(parents=True, exist_ok=True)
    envs_file = envs_dir / f"{session}.json"

    claude_bin = os.environ.get("CLAUDE_BIN_OVERRIDE")
    if claude_bin:
        argv = [claude_bin]
    else:
        argv = ["claude", "remote-control", "--name", session, *extra]

    # Capture stdout (and merge stderr into it) so we can scrape env_id from
    # the full output stream. The real `claude remote-control` TUI banner —
    # "Continue coding in the Claude app or https://claude.ai/code?environment=env_..."
    # — emits on stdout, not stderr. The original spike-era wrapper tailed
    # stderr only and silently dropped every env_id in production. Merging
    # also matches the session-manager.sh `>> log 2>&1` redirect downstream,
    # so no observable difference in the log file.
    child = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=sys.stdin,
        bufsize=1,
        text=True,
        # New session/process group so we can signal the whole tree, and so
        # PDEATHSIG (set in preexec) takes effect on the right boundary.
        start_new_session=True,
        preexec_fn=_set_pdeathsig,
    )

    def forward(signum, _frame):
        if child.poll() is None:
            try:
                # Forward to the entire process group — claude may have
                # spawned helpers (e.g. an MCP server) that should drain
                # together.
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    def tail_output():
        assert child.stdout is not None
        seen_env = False
        for line in child.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if seen_env:
                continue
            m = ENV_RE.search(line)
            if m:
                # Atomic write: temp + rename. Path.write_text truncates then
                # writes, so a reader that hits the truncate window sees an
                # empty file. The reaper observed exactly this race during the
                # Phase 2 soak (T+24h checkpoint, 2026-05-03 16:00:00):
                # `[reap] skip: no env_id in .../envs/willikins.json`. os.replace
                # is atomic on POSIX so the file is either old-content or
                # full-new-content, never partial.
                tmp = envs_file.with_suffix(envs_file.suffix + ".tmp")
                tmp.write_text(json.dumps({
                    "env_id": m.group(0),
                    "pid": child.pid,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }))
                os.replace(tmp, envs_file)
                seen_env = True

    t = threading.Thread(target=tail_output, daemon=True)
    t.start()

    rc = child.wait()
    t.join(timeout=2)

    if rc == 0:
        try:
            envs_file.unlink()
        except FileNotFoundError:
            pass

    return rc


if __name__ == "__main__":
    sys.exit(main())
