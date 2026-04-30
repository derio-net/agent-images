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

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ENV_RE = re.compile(r"env_[A-Za-z0-9_-]{6,}")


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

    child = subprocess.Popen(
        argv,
        stdout=sys.stdout,
        stderr=subprocess.PIPE,
        stdin=sys.stdin,
        bufsize=1,
        text=True,
    )

    def forward(signum, _frame):
        if child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    def tail_stderr():
        assert child.stderr is not None
        seen_env = False
        for line in child.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            if seen_env:
                continue
            m = ENV_RE.search(line)
            if m:
                envs_file.write_text(json.dumps({
                    "env_id": m.group(0),
                    "pid": child.pid,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }))
                seen_env = True

    t = threading.Thread(target=tail_stderr, daemon=True)
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
