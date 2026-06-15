"""Unit tests for the baked agent-session send/receive driver.

Ported from frank `scripts/tests/test_agent_session_driver.py`, re-pointed at
the BAKED image file instead of n8n's ConfigMap. The driver drives a persistent
agent TUI session (never `claude -p`):
  * submits via bracketed paste — `load-buffer` (stdin) + `paste-buffer -p` +
    a SEPARATE `send-keys Enter` after a settle delay (multi-line safe).
  * tells the agent to WRITE the JSON to a per-turn file (unique nonce path);
    the driver polls for that file to exist + parse, and that IS the payload.

`tmux` is faked via a PATH-injected Python stub (no real tmux needed): paste
stages the message, `send-keys Enter` makes the "agent" write the file the
message names. Env is the genericized `AGENT_SESSION_*`; a dedicated test
proves the deprecated `STOA_*` aliases still drive identical behaviour.

Modeled on the repo's existing pytest setup (`kali/tests/test_*.py`).
"""
import json
import os
import socket
import stat
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

import pytest

MAS = Path(__file__).resolve().parents[1]
DRIVER = MAS / "rootfs/usr/local/lib/multi-agent-shell/agent-session"
SERVICE_RUN = MAS / "rootfs/etc/services.d/agent-session-server/run"
SERVICE_FINISH = MAS / "rootfs/etc/services.d/agent-session-server/finish"

# The send/receive contract (inlined — the baked driver is a plain executable,
# not a ConfigMap, so there is no yaml to parse and no fixture file to read).
SEND_REQ = {
    "session_id": "agent-session-test",
    "agent": "claude",
    "message": "Investigate the surge and write a structured finding.",
    "timeout_s": 300,
}
RECV_KEYS = {"session_id", "agent", "status", "turn", "payload"}
PAYLOAD = {"finding": "traffic surge", "severity": "info", "sources": []}

# Fake tmux: load-buffer stages the message, paste-buffer holds it, send-keys
# Enter makes the "agent" write FAKE_PAYLOAD to the file the message names.
# `new-session` is logged verbatim so dispatch tests can assert the launch cmd.
FAKE_TMUX = r'''#!/usr/bin/env python3
import sys, os, re
D = os.environ["FAKE_DIR"]
def p(n): return os.path.join(D, n)
a = sys.argv[1:]
cmd = a[0] if a else ""
open(p("calls.log"), "a").write(cmd + " " + " ".join(a[1:]) + "\n")
if cmd == "has-session":
    try: code = int((open(p("has.code")).read().strip() or "0"))
    except Exception: code = 0
    sys.exit(code)
if cmd == "new-session":
    open(p("new.log"), "a").write(" ".join(a) + "\n"); sys.exit(0)
if cmd == "load-buffer":
    open(p("buffer.txt"), "w").write(sys.stdin.read()); sys.exit(0)
if cmd == "paste-buffer":
    buf = open(p("buffer.txt")).read() if os.path.exists(p("buffer.txt")) else ""
    open(p("pending.txt"), "w").write(buf); sys.exit(0)
if cmd == "send-keys":
    if "Enter" in a and os.environ.get("FAKE_NO_REPLY") != "1":
        msg = open(p("pending.txt")).read() if os.path.exists(p("pending.txt")) else ""
        m = re.search(r"to the file (\S+)", msg)
        if m:
            outfile = m.group(1)
            os.makedirs(os.path.dirname(outfile), exist_ok=True)
            open(outfile, "w").write(os.environ.get("FAKE_PAYLOAD", "{}"))
    sys.exit(0)
sys.exit(0)
'''


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


def _make_harness(tmp_path, *, env_prefix="AGENT_SESSION_"):
    """Build a driver harness. env_prefix selects the new (AGENT_SESSION_) or
    the deprecated (STOA_) env var family so the alias path is exercisable."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    drv = bindir / "agent-session"; drv.write_text(DRIVER.read_text())
    drv.chmod(drv.stat().st_mode | stat.S_IEXEC)
    faketmux = bindir / "tmux"; faketmux.write_text(FAKE_TMUX)
    faketmux.chmod(faketmux.stat().st_mode | stat.S_IEXEC)
    fdir = tmp_path / "fake"; fdir.mkdir()
    home = tmp_path / "home"; home.mkdir()  # isolate HOME so pretrust() never touches real ~/.claude.json

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HOME"] = str(home)
    env["FAKE_DIR"] = str(fdir)
    env[env_prefix + "TURN_DIR"] = str(tmp_path / "turns")
    env[env_prefix + "OUT_DIR"] = str(tmp_path / "out")
    env[env_prefix + "POLL_S"] = "0.05"
    env[env_prefix + "SETTLE_S"] = "0"
    env["FAKE_PAYLOAD"] = json.dumps(PAYLOAD)

    def run(req, session_exists=True, no_reply=False):
        (fdir / "has.code").write_text("0" if session_exists else "1")
        e = dict(env)
        if no_reply:
            e["FAKE_NO_REPLY"] = "1"
        return subprocess.run([sys.executable, str(drv), "send", json.dumps(req)],
                              capture_output=True, text=True, env=e, timeout=30)

    return types.SimpleNamespace(drv=drv, env=env, fdir=fdir, home=home, run=run)


@pytest.fixture
def harness(tmp_path):
    return _make_harness(tmp_path)


def test_receive_shape_matches_contract(harness):
    out = json.loads(harness.run(SEND_REQ).stdout)
    assert set(out) == RECV_KEYS, f"keys {set(out)} != contract {RECV_KEYS}"
    assert out["status"] == "ok"
    assert out["session_id"] == SEND_REQ["session_id"]
    assert out["agent"] == "claude"
    assert out["payload"] == PAYLOAD, "payload must come from the file the agent wrote"


def test_submits_via_bracketed_paste_not_send_keys_text(harness):
    harness.run(SEND_REQ)
    calls = (harness.fdir / "calls.log").read_text()
    assert "load-buffer" in calls and "paste-buffer" in calls, "must paste the message"
    # The message must NOT be typed as send-keys literal text (the swallowed-Enter
    # bug): the only send-keys call is the bare Enter submit.
    sk_lines = [l for l in calls.splitlines() if l.startswith("send-keys")]
    assert sk_lines, "must submit with send-keys Enter"
    assert all("Enter" in l for l in sk_lines), f"send-keys must only send Enter, got {sk_lines}"


def test_payload_from_file_not_pane(harness):
    out = json.loads(harness.run(SEND_REQ).stdout)
    assert out["status"] == "ok" and out["payload"] == PAYLOAD


def test_unique_file_per_turn(harness):
    a = json.loads(harness.run(SEND_REQ).stdout)
    b = json.loads(harness.run(SEND_REQ).stdout)
    assert a["status"] == "ok" and b["status"] == "ok"
    assert b["turn"] == a["turn"] + 1


def test_auto_creates_missing_session(harness):
    out = json.loads(harness.run(SEND_REQ, session_exists=False).stdout)
    assert out["status"] == "ok"
    newlog = (harness.fdir / "new.log").read_text()
    assert SEND_REQ["session_id"] in newlog
    assert "--permission-mode auto" in newlog


def test_auto_create_pretrusts_workspace(harness):
    harness.run(SEND_REQ, session_exists=False)
    cfg = harness.home / ".claude.json"
    assert cfg.exists(), "pretrust must write ~/.claude.json"
    proj = json.loads(cfg.read_text()).get("projects", {})
    assert proj.get(str(harness.home), {}).get("hasTrustDialogAccepted") is True


def test_timeout_when_no_file(harness):
    req = dict(SEND_REQ, timeout_s=0.3)
    out = json.loads(harness.run(req, no_reply=True).stdout)
    assert out["status"] != "ok"


def test_deprecated_stoa_aliases_still_drive(tmp_path):
    # A consumer mid-migration that sets only the legacy STOA_* vars must get
    # identical behaviour (the deprecated-alias fallback, kept for one cycle).
    h = _make_harness(tmp_path, env_prefix="STOA_")
    out = json.loads(h.run(SEND_REQ).stdout)
    assert out["status"] == "ok" and out["payload"] == PAYLOAD
    # The turn dir the legacy var named must be the one actually used.
    assert (tmp_path / "turns" / (SEND_REQ["session_id"] + ".turn")).exists()


@pytest.mark.parametrize("agent,expected_launch", [
    ("claude", "claude --permission-mode auto"),
    ("codex", "codex --full-auto"),
    ("antigravity", "agy --yolo"),
])
def test_per_agent_launch_profile(harness, agent, expected_launch):
    # ensure_session dispatches on the `agent` field via the launch-profile
    # table; the FAKE_TMUX records the new-session command verbatim.
    harness.run(dict(SEND_REQ, agent=agent), session_exists=False)
    newlog = (harness.fdir / "new.log").read_text()
    assert expected_launch in newlog, \
        f"agent {agent!r} must launch via `{expected_launch}`, got: {newlog!r}"


def test_unknown_agent_falls_back_to_claude(harness):
    # An unrecognized agent must not crash — default to the verified claude
    # profile rather than launching nothing.
    harness.run(dict(SEND_REQ, agent="nope-not-an-agent"), session_exists=False)
    newlog = (harness.fdir / "new.log").read_text()
    assert "claude --permission-mode auto" in newlog


def test_s6_service_run_gated_on_serve_flag():
    # The baked s6 longrun serves agent-session ONLY when AGENT_SESSION_SERVE=1
    # (default off — a plain interactive shell is unaffected; consumers opt in).
    assert SERVICE_RUN.exists(), "agent-session-server s6 run script must exist"
    text = SERVICE_RUN.read_text()
    assert text.startswith("#!/command/with-contenv bash"), "must mirror the sshd s6 shebang"
    assert "AGENT_SESSION_SERVE" in text, "serve must be gated on AGENT_SESSION_SERVE"
    assert "agent-session serve" in text, "must exec the baked agent-session serve"
    # s6 supervises restarts, so there is NO busy while/sleep loop; when not
    # opted in the service idles (sleep infinity) so s6 sees it as up.
    assert "sleep infinity" in text, "must idle (not exit) when not opted in"
    # Check for an actual `while` loop construct, ignoring the word in comments.
    code = [l.split("#", 1)[0].strip() for l in text.splitlines()]
    assert not any(l.startswith("while") for l in code), \
        "s6 supervises restarts; no while/sleep loop"


def test_s6_service_finish_mirrors_sshd():
    assert SERVICE_FINISH.exists(), "agent-session-server s6 finish script must exist"
    assert SERVICE_FINISH.read_text().startswith("#!/command/with-contenv bash")


def test_http_server_serves_session_send(harness):
    port = _free_port()
    (harness.fdir / "has.code").write_text("0")
    env = dict(harness.env); env["AGENT_SESSION_PORT"] = str(port)
    proc = subprocess.Popen([sys.executable, str(harness.drv), "serve"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("server did not become ready")
        body = json.dumps(SEND_REQ).encode()
        req = urllib.request.Request(base + "/session/send", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read())
        assert out["status"] == "ok" and out["payload"] == PAYLOAD
    finally:
        proc.terminate(); proc.wait(timeout=5)
