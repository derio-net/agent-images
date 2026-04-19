#!/usr/bin/env bash
# Integration tests for scripts/shutdown.sh.
#
# Covers:
#   1. SIGTERM-on-exit: a cooperating child receives SIGTERM, exits, pidfile removed.
#   2. SIGKILL fallback: a child that ignores SIGTERM gets killed after the grace window.
#   3. Stale pidfile: pidfile whose PID is already dead is cleaned without error.
#   4. Empty PIDDIR: shutdown.sh is a no-op and exits 0.
#   5. Malformed pidfile content is cleaned.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SHUTDOWN="$REPO_ROOT/scripts/shutdown.sh"

[[ -x "$SHUTDOWN" ]] || { echo "FAIL: $SHUTDOWN missing or not executable"; exit 1; }

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# Each test gets its own isolated WILLIKINS_AGENT_DIR.
make_env() {
    local dir
    dir="$(mktemp -d)"
    mkdir -p "$dir/pids"
    printf '%s' "$dir"
}

# ── Test 1: cooperating child exits on SIGTERM ──────────────────────────────
test_graceful_sigterm() {
    local agent_dir
    agent_dir="$(make_env)"

    bash -c 'trap "exit 0" TERM; sleep 60 & wait $!' &
    local pid=$!
    echo "$pid" > "$agent_dir/pids/willikins.pid"
    # Give bash a moment to install the trap.
    sleep 0.2
    kill -0 "$pid" || fail "graceful: child didn't start (pid $pid)"

    WILLIKINS_AGENT_DIR="$agent_dir" SHUTDOWN_GRACE_SECONDS=5 \
        bash "$SHUTDOWN" >/dev/null

    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
        fail "graceful: child $pid still alive after shutdown.sh"
    fi
    [[ -f "$agent_dir/pids/willikins.pid" ]] && fail "graceful: pidfile not cleaned"
    rm -rf "$agent_dir"
    pass "graceful SIGTERM"
}

# ── Test 2: uncooperative child is SIGKILLed after the grace window ─────────
test_sigkill_fallback() {
    local agent_dir
    agent_dir="$(make_env)"

    # Ignore SIGTERM entirely so shutdown.sh must fall through to SIGKILL.
    bash -c 'trap "" TERM; sleep 60 & wait $!' &
    local pid=$!
    echo "$pid" > "$agent_dir/pids/stuck.pid"
    sleep 0.2
    kill -0 "$pid" || fail "sigkill: child didn't start"

    local start=$SECONDS
    WILLIKINS_AGENT_DIR="$agent_dir" SHUTDOWN_GRACE_SECONDS=2 \
        bash "$SHUTDOWN" >/dev/null
    local elapsed=$((SECONDS - start))

    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
        fail "sigkill: child $pid still alive after grace period"
    fi
    (( elapsed >= 2 )) || fail "sigkill: returned too early (${elapsed}s, expected >=2)"
    (( elapsed < 10 )) || fail "sigkill: hung (${elapsed}s)"
    [[ -f "$agent_dir/pids/stuck.pid" ]] && fail "sigkill: pidfile not cleaned"
    rm -rf "$agent_dir"
    pass "SIGKILL fallback"
}

# ── Test 3: stale pidfile whose PID is already dead is cleaned ──────────────
test_stale_pidfile() {
    local agent_dir
    agent_dir="$(make_env)"

    # Start then immediately kill a child to get a pid that is recycle-safe
    # enough for a fast test: shell's own dead children aren't reused while
    # unreaped, but we're running under a parent that won't reap fast here.
    # Use a very large unlikely PID instead.
    echo "2147483600" > "$agent_dir/pids/ghost.pid"

    WILLIKINS_AGENT_DIR="$agent_dir" SHUTDOWN_GRACE_SECONDS=2 \
        bash "$SHUTDOWN" >/dev/null

    [[ -f "$agent_dir/pids/ghost.pid" ]] && fail "stale: pidfile not cleaned"
    rm -rf "$agent_dir"
    pass "stale pidfile"
}

# ── Test 4: no pidfiles at all — clean exit ─────────────────────────────────
test_no_pidfiles() {
    local agent_dir
    agent_dir="$(make_env)"
    WILLIKINS_AGENT_DIR="$agent_dir" bash "$SHUTDOWN" >/dev/null
    rm -rf "$agent_dir"
    pass "no pidfiles"
}

# ── Test 5: malformed pidfile content is removed ────────────────────────────
test_malformed_pidfile() {
    local agent_dir
    agent_dir="$(make_env)"
    printf 'not-a-pid\n' > "$agent_dir/pids/junk.pid"
    : > "$agent_dir/pids/empty.pid"

    WILLIKINS_AGENT_DIR="$agent_dir" bash "$SHUTDOWN" >/dev/null

    [[ -f "$agent_dir/pids/junk.pid" ]] && fail "malformed: junk pidfile not cleaned"
    [[ -f "$agent_dir/pids/empty.pid" ]] && fail "malformed: empty pidfile not cleaned"
    rm -rf "$agent_dir"
    pass "malformed pidfile"
}

test_graceful_sigterm
test_sigkill_fallback
test_stale_pidfile
test_no_pidfiles
test_malformed_pidfile

echo "ALL OK"
