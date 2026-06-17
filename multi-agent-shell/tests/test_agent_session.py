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
import importlib.machinery
import importlib.util
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
def _target(args):
    if "-t" in args:
        i = args.index("-t")
        if i + 1 < len(args):
            return args[i + 1]
    return ""
if cmd == "kill-session":
    # Record the killed session id so capture-pane can flip a DEAD session to a
    # ready REPL after the driver recreates it (Fix C liveness recreate path).
    open(p("killed.log"), "a").write(_target(a) + "\n")
    sys.exit(0)
if cmd == "has-session":
    try: code = int((open(p("has.code")).read().strip() or "0"))
    except Exception: code = 0
    sys.exit(code)
if cmd == "new-session":
    open(p("new.log"), "a").write(" ".join(a) + "\n"); sys.exit(0)
if cmd == "load-buffer":
    data = sys.stdin.read()
    open(p("buffer.txt"), "w").write(data)
    # Record the first line of every pasted buffer so tests can assert the
    # ordering of control submits (/clear, /compact) relative to the message.
    open(p("pastes.log"), "a").write((data.splitlines()[0] if data else "") + "\n")
    sys.exit(0)
if cmd == "paste-buffer":
    buf = open(p("buffer.txt")).read() if os.path.exists(p("buffer.txt")) else ""
    open(p("pending.txt"), "w").write(buf); sys.exit(0)
if cmd == "send-keys":
    if "Enter" in a and os.environ.get("FAKE_NO_REPLY") != "1":
        ec = p("enter.count")
        k = int(open(ec).read() or "0") if os.path.exists(ec) else 0
        open(ec, "w").write(str(k + 1))
        if k < int(os.environ.get("FAKE_DROP_FIRST_ENTER", "0")):
            # Dropped Enter (cold TUI / first-run interstitial): the message stays
            # stuck in the input box instead of submitting.
            pend = open(p("pending.txt")).read() if os.path.exists(p("pending.txt")) else ""
            open(p("box.txt"), "w").write(pend[:40])
        else:
            open(p("box.txt"), "w").write("")   # submitted → input box clears
            msg = open(p("pending.txt")).read() if os.path.exists(p("pending.txt")) else ""
            m = re.search(r"to the file (\S+)", msg)
            if m:
                outfile = m.group(1)
                os.makedirs(os.path.dirname(outfile), exist_ok=True)
                open(outfile, "w").write(os.environ.get("FAKE_PAYLOAD", "{}"))
    sys.exit(0)
if cmd == "capture-pane":
    cc = p("capture.count")
    n = int(open(cc).read() or "0") if os.path.exists(cc) else 0
    open(cc, "w").write(str(n + 1))
    tgt = _target(a)
    killed = bool(tgt) and os.path.exists(p("killed.log")) and tgt in open(p("killed.log")).read().split()
    if os.environ.get("FAKE_DEAD_SESSION") == "1" and not killed:
        # An EXISTING but DEAD session (continuum-restored bash shell / crashed
        # claude): a stable shell prompt, NO ❯, until the driver KILLS + recreates
        # it — after the kill marker the recreated session renders the ready ❯.
        sys.stdout.write("agent@pod:~$ \n")
    elif n < int(os.environ.get("FAKE_COLD_CAPTURES", "0")):
        sys.stdout.write("")            # cold boot: REPL not ready → empty pane
    else:
        box = open(p("box.txt")).read() if os.path.exists(p("box.txt")) else ""
        # ready pane: the ❯ prompt (with any unsubmitted box text after it) + status line.
        # FAKE_HISTORY_PROMPT adds a transcript line that ALSO contains ❯ above the
        # input box — the driver must read the LAST ❯ line (the box), not this one.
        history = "echoed ❯ old input\n" if os.environ.get("FAKE_HISTORY_PROMPT") == "1" else "some history\n"
        # Optional context-usage indicator line (Fix E 60% compaction). The exact
        # live string is a live-verify item (P2.T3.S2); the stub emits the parser's
        # target form ("context: NN% used") so the unit path is exercisable.
        ctx = ("context: " + os.environ["FAKE_CONTEXT_PCT"] + "% used\n") if os.environ.get("FAKE_CONTEXT_PCT") else ""
        sys.stdout.write(history + "❯ " + box + "\n⏵⏵ auto mode on\n" + ctx)
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
    env[env_prefix + "LAST_DIR"] = str(tmp_path / "last")
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


@pytest.mark.parametrize("agent,expected_tokens", [
    # claude embeds a per-session --session-id uuid (Fix E); codex/antigravity
    # profiles are unchanged. Token-list assertion tolerates the injected uuid.
    ("claude", ["claude", "--session-id", "--permission-mode auto"]),
    ("codex", ["codex --full-auto"]),
    ("antigravity", ["agy --yolo"]),
])
def test_per_agent_launch_profile(harness, agent, expected_tokens):
    # ensure_session dispatches on the `agent` field via the launch-profile
    # table; the FAKE_TMUX records the new-session command verbatim.
    harness.run(dict(SEND_REQ, agent=agent), session_exists=False)
    newlog = (harness.fdir / "new.log").read_text()
    for tok in expected_tokens:
        assert tok in newlog, \
            f"agent {agent!r} launch missing {tok!r}, got: {newlog!r}"


def test_unknown_agent_falls_back_to_claude(harness):
    # An unrecognized agent must not crash — default to the verified claude
    # profile rather than launching nothing.
    harness.run(dict(SEND_REQ, agent="nope-not-an-agent"), session_exists=False)
    newlog = (harness.fdir / "new.log").read_text()
    assert "claude --permission-mode auto" in newlog


# --- Cold-start reliability (A1 readiness gate, A3 verified submit, A2 flag) ----

def _enter_count(harness):
    log = (harness.fdir / "calls.log").read_text()
    return len([l for l in log.splitlines() if l.startswith("send-keys") and "Enter" in l])


def test_waits_for_ready_before_submit(tmp_path):
    # A1: a fresh session whose pane is empty for the first 3 captures (cold boot)
    # must NOT submit until the REPL prompt renders — the readiness gate polls past
    # the cold captures, so the submit lands and the turn completes.
    h = _make_harness(tmp_path)
    h.env["FAKE_COLD_CAPTURES"] = "3"
    e = dict(h.env)
    (h.fdir / "has.code").write_text("1")   # session missing → created → gated
    out = json.loads(subprocess.run(
        [sys.executable, str(h.drv), "send", json.dumps(SEND_REQ)],
        capture_output=True, text=True, env=e, timeout=30).stdout)
    assert out["status"] == "ok"
    assert int((h.fdir / "capture.count").read_text()) >= 3, "must have polled the cold pane"


def test_readiness_gate_times_out_gracefully(tmp_path):
    # A1: if the pane never becomes ready, the gate must time out and proceed
    # best-effort (never hang the request).
    h = _make_harness(tmp_path)
    h.env["FAKE_COLD_CAPTURES"] = "100000"
    h.env["AGENT_SESSION_READY_TIMEOUT_S"] = "0.3"
    e = dict(h.env)
    (h.fdir / "has.code").write_text("1")
    res = subprocess.run([sys.executable, str(h.drv), "send", json.dumps(SEND_REQ)],
                         capture_output=True, text=True, env=e, timeout=15)
    out = json.loads(res.stdout)   # returns (does not hang) — submit still ran
    assert out["status"] == "ok"


def test_verified_submit_retries_dropped_enter(tmp_path):
    # A3: the first Enter is dropped (cold TUI / interstitial) leaving the message
    # in the input box — the verified submit must re-press Enter so it lands.
    h = _make_harness(tmp_path)
    h.env["FAKE_DROP_FIRST_ENTER"] = "1"
    e = dict(h.env)
    (h.fdir / "has.code").write_text("0")   # warm session → no readiness gate
    out = json.loads(subprocess.run(
        [sys.executable, str(h.drv), "send", json.dumps(SEND_REQ)],
        capture_output=True, text=True, env=e, timeout=30).stdout)
    assert out["status"] == "ok" and out["payload"] == PAYLOAD
    assert _enter_count(h) == 2, "must retry Enter exactly once when the box didn't clear"


def test_warm_submit_does_not_double_enter(harness):
    # A3: when the first Enter submits cleanly, there must be NO spurious retry.
    harness.run(SEND_REQ)   # warm session, default envs
    assert _enter_count(harness) == 1


def test_verified_submit_ignores_transcript_prompt_glyph(tmp_path):
    # A3 hardening: a ❯ in the transcript (echoed output) above an EMPTY input box
    # must not be mistaken for an unsubmitted message — the box is the LAST ❯ line.
    # With a top-down scan this would spuriously retry; bottom-up reads the empty box.
    h = _make_harness(tmp_path)
    h.env["FAKE_HISTORY_PROMPT"] = "1"
    e = dict(h.env)
    (h.fdir / "has.code").write_text("0")   # warm; clean first-Enter submit clears the box
    out = json.loads(subprocess.run(
        [sys.executable, str(h.drv), "send", json.dumps(SEND_REQ)],
        capture_output=True, text=True, env=e, timeout=30).stdout)
    assert out["status"] == "ok"
    assert _enter_count(h) == 1, "a transcript ❯ must not trigger the verified-submit retry"


def test_pretrust_seeds_auto_mode_flag(harness):
    # A2: pretrust seeds the auto-mode-entry warning flag alongside the trust flag,
    # so a fresh profile's first --permission-mode auto entry swallows no Enter.
    harness.run(SEND_REQ, session_exists=False)
    proj = json.loads((harness.home / ".claude.json").read_text()).get("projects", {})
    assert proj.get(str(harness.home), {}).get("hasSeenAutoModeEntryWarning") is True


# --- Fix C: driver liveness check (never trust a dead existing session) -------

def test_dead_existing_session_is_recreated(tmp_path):
    # has-session reports the session EXISTS, but its pane is a dead bash shell
    # (continuum-restored / crashed claude — no ❯). The driver must detect this,
    # kill the dead session, recreate it, and submit to the fresh REPL.
    h = _make_harness(tmp_path)
    h.env["FAKE_DEAD_SESSION"] = "1"
    h.env["AGENT_SESSION_READY_PROBE_S"] = "0.3"   # short bound so the probe gives up fast
    e = dict(h.env)
    (h.fdir / "has.code").write_text("0")          # session EXISTS (but dead)
    out = json.loads(subprocess.run(
        [sys.executable, str(h.drv), "send", json.dumps(SEND_REQ)],
        capture_output=True, text=True, env=e, timeout=30).stdout)
    assert out["status"] == "ok" and out["payload"] == PAYLOAD
    calls = (h.fdir / "calls.log").read_text().splitlines()
    sid = SEND_REQ["session_id"]
    kill_idx = next((i for i, l in enumerate(calls)
                     if l.startswith("kill-session") and sid in l), None)
    new_idx = next((i for i, l in enumerate(calls)
                    if l.startswith("new-session") and sid in l), None)
    assert kill_idx is not None, f"dead session must be killed; calls={calls}"
    assert new_idx is not None and new_idx > kill_idx, \
        f"must recreate AFTER killing the dead session; calls={calls}"


def test_live_existing_session_is_reused(tmp_path):
    # A live ❯ REPL that already exists must be reused untouched — no kill, no
    # recreate (warm path, no added latency beyond a single readiness capture).
    h = _make_harness(tmp_path)
    e = dict(h.env)
    (h.fdir / "has.code").write_text("0")          # exists + (default) ready ❯ pane
    out = json.loads(subprocess.run(
        [sys.executable, str(h.drv), "send", json.dumps(SEND_REQ)],
        capture_output=True, text=True, env=e, timeout=30).stdout)
    assert out["status"] == "ok"
    calls = (h.fdir / "calls.log").read_text()
    assert "kill-session" not in calls, f"a live session must not be killed; calls={calls!r}"


def test_absent_session_still_creates(tmp_path):
    # Regression: a genuinely-absent session still takes the create + wait_ready
    # path (Fix C must not break the original cold-create flow).
    h = _make_harness(tmp_path)
    e = dict(h.env)
    (h.fdir / "has.code").write_text("1")          # session ABSENT
    out = json.loads(subprocess.run(
        [sys.executable, str(h.drv), "send", json.dumps(SEND_REQ)],
        capture_output=True, text=True, env=e, timeout=30).stdout)
    assert out["status"] == "ok"
    assert SEND_REQ["session_id"] in (h.fdir / "new.log").read_text()
    assert "kill-session" not in (h.fdir / "calls.log").read_text()


# --- Fix E: persistent --session-id sessions + idle /clear + 60% compaction ----

def _driver_module():
    # Import the baked driver as a module (no .py suffix → load by path) so unit
    # tests can call its pure helpers (session_uuid, context_pct) directly. The
    # __main__ guard prevents main() from running on import.
    loader = importlib.machinery.SourceFileLoader("agent_session_drv", str(DRIVER))
    spec = importlib.util.spec_from_loader("agent_session_drv", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)   # DRIVER has no .py suffix → explicit SourceFileLoader
    return mod


def _paste_first_lines(harness):
    pl = harness.fdir / "pastes.log"
    return pl.read_text().splitlines() if pl.exists() else []


def test_session_uuid_is_deterministic():
    import uuid
    mod = _driver_module()
    a = mod.session_uuid("alert-agent-tg-2034763022")
    b = mod.session_uuid("alert-agent-tg-2034763022")
    c = mod.session_uuid("alert-agent-ops")
    assert a == b, "same session_id must map to the same uuid (resume across restarts)"
    assert uuid.UUID(a), "must be a valid UUID for claude --session-id"
    assert a != c, "different session_ids must map to different uuids"


def test_launch_uses_session_id_uuid(harness):
    # claude launches with --session-id <uuid5(session_id)> so the conversation
    # persists/resumes on the PVC across pod restarts.
    mod = _driver_module()
    harness.run(SEND_REQ, session_exists=False)
    newlog = (harness.fdir / "new.log").read_text()
    expected = mod.session_uuid(SEND_REQ["session_id"])
    assert f"--session-id {expected}" in newlog, \
        f"launch must pin the deterministic session uuid, got: {newlog!r}"
    assert "--permission-mode auto" in newlog


def test_idle_over_12h_clears_first(harness):
    # A persisted conversation idle > 12h must be /clear'd (fresh conversation,
    # SAME uuid) BEFORE the new message, and last_activity refreshed.
    sid = SEND_REQ["session_id"]
    last_dir = Path(harness.env["AGENT_SESSION_LAST_DIR"]); last_dir.mkdir(parents=True, exist_ok=True)
    la = last_dir / (sid + ".last")
    old = time.time() - (13 * 3600)
    la.write_text(str(old))
    out = json.loads(harness.run(SEND_REQ).stdout)   # has.code defaults to live (0)
    assert out["status"] == "ok"
    pastes = _paste_first_lines(harness)
    assert "/clear" in pastes, f"idle>12h must submit /clear; pastes={pastes}"
    assert pastes.index("/clear") < next(i for i, l in enumerate(pastes) if l.startswith("Investigate")), \
        f"/clear must precede the message; pastes={pastes}"
    assert float(la.read_text()) > old, "last_activity must be refreshed after the turn"


def test_recent_activity_no_clear(harness):
    # Recent activity (< 12h) must NOT clear — the conversation continues.
    sid = SEND_REQ["session_id"]
    last_dir = Path(harness.env["AGENT_SESSION_LAST_DIR"]); last_dir.mkdir(parents=True, exist_ok=True)
    (last_dir / (sid + ".last")).write_text(str(time.time()))
    out = json.loads(harness.run(SEND_REQ).stdout)
    assert out["status"] == "ok"
    assert "/clear" not in _paste_first_lines(harness), "recent activity must not /clear"


def test_context_pct_parses():
    cp = _driver_module().context_pct
    assert cp("context: 70% used\n❯ ") == 70
    assert cp("Context left until auto-compact: 30%") == 70, "'left' wording must invert to % used"
    assert cp("no indicator here\n❯ ") is None
    assert cp("❯ \n⏵⏵ auto mode on\n") is None


def _run_with_ctx(harness, pct):
    e = dict(harness.env)
    if pct is not None:
        e["FAKE_CONTEXT_PCT"] = str(pct)
    (harness.fdir / "has.code").write_text("0")   # live session
    return json.loads(subprocess.run(
        [sys.executable, str(harness.drv), "send", json.dumps(SEND_REQ)],
        capture_output=True, text=True, env=e, timeout=30).stdout)


def test_compacts_when_context_over_threshold(harness):
    # >= 60% context used after a successful turn → proactive /compact.
    out = _run_with_ctx(harness, 70)
    assert out["status"] == "ok"
    assert "/compact" in _paste_first_lines(harness), "must /compact at 70% used"


def test_no_compact_under_threshold(harness):
    out = _run_with_ctx(harness, 40)
    assert out["status"] == "ok"
    assert "/compact" not in _paste_first_lines(harness), "must NOT /compact at 40% used"


def test_no_compact_when_indicator_absent(harness):
    # Unparseable/absent indicator → defer to claude auto-compact (no /compact, no crash).
    out = _run_with_ctx(harness, None)
    assert out["status"] == "ok"
    assert "/compact" not in _paste_first_lines(harness)


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
