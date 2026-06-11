#!/usr/bin/env bash
# test_session_manager.sh — harness for scripts/session-manager.sh
# Focus: uptime-rotation guard (#88) + spawn/already-running paths.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SCRIPT_DIR/scripts/session-manager.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/h"
export AGENT_HOME="$HOME"
mkdir -p "$HOME"

# Fake repo + session config.
REPO="$TMP/repo"
mkdir -p "$REPO/.git"
export WILLIKINS_REPOS="$REPO:testsess"

# Stub supervisor: sleeps like a healthy long-running session. Must be python
# (session-manager spawns `python3 -u $WRAP_CLAUDE`). Ignores stdin/args.
export WRAP_CLAUDE="$TMP/wrap-stub.py"
cat > "$WRAP_CLAUDE" <<'EOS'
import time
time.sleep(600)
EOS

# Keep the run hermetic: no orphan reaping, heartbeat fails fast + non-fatal.
export REAP_ORPHAN_ENVS=0
export PUSHGATEWAY_URL="http://127.0.0.1:1"

LOG="$HOME/.willikins-agent/session-manager.log"
PIDFILE="$HOME/.willikins-agent/pids/testsess.pid"
NOW_HOUR=$((10#$(date -u +%H)))

run_sm() { bash "$SCRIPT" >/dev/null 2>&1; }

# --- Case 1: fresh spawn — pidfile written, process alive, debug-file flag passed ---
export ROTATE_UTC_HOUR=$NOW_HOUR
run_sm
[[ -f "$PIDFILE" ]] || { echo "FAIL: no pidfile after fresh spawn" >&2; cat "$LOG" >&2; exit 1; }
PID1=$(cat "$PIDFILE")
sleep 0.5
kill -0 "$PID1" || { echo "FAIL: spawned session not alive" >&2; cat "$LOG" >&2; exit 1; }
grep -q "Starting session 'testsess'" "$LOG" || { echo "FAIL: spawn not logged" >&2; cat "$LOG" >&2; exit 1; }

# --- Case 2: young session, window open — no rotation ---
run_sm
PID2=$(cat "$PIDFILE")
[[ "$PID2" == "$PID1" ]] || { echo "FAIL: young session was respawned" >&2; cat "$LOG" >&2; exit 1; }
grep -q "already running (PID $PID1)" "$LOG" || { echo "FAIL: already-running not logged" >&2; cat "$LOG" >&2; exit 1; }

# --- Case 3: over-age session OUTSIDE the rotation window — no rotation ---
# +12h so an hour rollover during the test run can't open the window.
export MAX_SESSION_UPTIME_S=1
export ROTATE_UTC_HOUR=$(( (NOW_HOUR + 12) % 24 ))
sleep 2   # let etime exceed the 1s threshold
run_sm
PID3=$(cat "$PIDFILE")
[[ "$PID3" == "$PID1" ]] || { echo "FAIL: rotated outside the window" >&2; cat "$LOG" >&2; exit 1; }

# --- Case 4: over-age session, rotation DISABLED (0) — no rotation ---
export MAX_SESSION_UPTIME_S=0
export ROTATE_UTC_HOUR=$((10#$(date -u +%H)))   # re-read: window must be open NOW
run_sm
PID4=$(cat "$PIDFILE")
[[ "$PID4" == "$PID1" ]] || { echo "FAIL: rotated despite MAX_SESSION_UPTIME_S=0" >&2; cat "$LOG" >&2; exit 1; }

# --- Case 5: over-age session inside the window — SIGTERM + respawn ---
export MAX_SESSION_UPTIME_S=1
export ROTATE_UTC_HOUR=$((10#$(date -u +%H)))   # re-read: window must be open NOW
run_sm
PID5=$(cat "$PIDFILE")
[[ "$PID5" != "$PID1" ]] || { echo "FAIL: over-age session not rotated" >&2; cat "$LOG" >&2; exit 1; }
kill -0 "$PID1" 2>/dev/null && { echo "FAIL: old session still alive after rotation" >&2; cat "$LOG" >&2; exit 1; }
sleep 0.5
kill -0 "$PID5" || { echo "FAIL: replacement session not alive" >&2; cat "$LOG" >&2; exit 1; }
grep -q "Session 'testsess' rotating: etime=" "$LOG" || { echo "FAIL: rotation not logged" >&2; cat "$LOG" >&2; exit 1; }

# Cleanup the survivor.
kill "$PID5" 2>/dev/null || true

echo PASS
