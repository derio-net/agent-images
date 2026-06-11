#!/usr/bin/env bash
# test_npm_cache_prune.sh — harness for scripts/npm-cache-prune.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SCRIPT_DIR/scripts/npm-cache-prune.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

run_with_npm_stub() {
    # $1: npm exit code
    local rc="$1"
    cat > "$STUB_BIN/npm" <<EOS
#!/usr/bin/env bash
echo "npm cache verify (stub) called"
exit $rc
EOS
    chmod +x "$STUB_BIN/npm"
}

setup_fixture() {
    rm -rf "$AGENT_HOME"
    mkdir -p "$AGENT_HOME/.npm/_cacache/content-v2" "$AGENT_HOME/.willikins-agent"

    # Old file (atime 8 days ago) — must be deleted.
    old="$AGENT_HOME/.npm/_cacache/content-v2/old.tgz"
    echo old > "$old"
    touch -a -t "$(date -u -d '8 days ago' +%Y%m%d%H%M)" "$old"

    # Fresh file (atime now) — must remain.
    fresh="$AGENT_HOME/.npm/_cacache/content-v2/fresh.tgz"
    echo fresh > "$fresh"
    touch -a "$fresh"
}

export AGENT_HOME="$TMP/h"
export HOME="$AGENT_HOME"
STUB_BIN="$TMP/bin"
mkdir -p "$STUB_BIN"
export PATH="$STUB_BIN:$PATH"

# --- Case 1: happy path ---
setup_fixture
run_with_npm_stub 0
rc=0
bash "$SCRIPT" >"$TMP/out.log" 2>&1 || rc=$?
[[ $rc -eq 0 ]] || { echo "FAIL: happy path exit=$rc" >&2; cat "$TMP/out.log" >&2; exit 1; }
[[ ! -e "$old" ]]   || { echo "FAIL: old file still present" >&2; cat "$TMP/out.log" >&2; exit 1; }
[[   -e "$fresh" ]] || { echo "FAIL: fresh file deleted" >&2; cat "$TMP/out.log" >&2; exit 1; }
grep -q "npm cache verify" "$TMP/out.log" || { echo "FAIL: verify not invoked" >&2; cat "$TMP/out.log" >&2; exit 1; }

# --- Case 2: empty state (no cache dir) ---
rm -rf "$AGENT_HOME/.npm"
bash "$SCRIPT" >"$TMP/out2.log" 2>&1
grep -q "nothing to prune" "$TMP/out2.log" || { echo "FAIL: empty-state path silent" >&2; cat "$TMP/out2.log" >&2; exit 1; }

# --- Case 3: npm cache verify exits non-zero — script should propagate non-zero exit ---
setup_fixture
run_with_npm_stub 7
rc=0
bash "$SCRIPT" >"$TMP/out3.log" 2>&1 || rc=$?
[[ $rc -eq 7 ]] || { echo "FAIL: expected exit 7 from failing npm, got $rc" >&2; cat "$TMP/out3.log" >&2; exit 1; }
grep -q "WARN: npm cache verify exited 7" "$TMP/out3.log" || { echo "FAIL: warn not logged" >&2; cat "$TMP/out3.log" >&2; exit 1; }

# --- Case 4: stale npx swap remnants swept; fresh remnants, real packages,
# .bin, and package-internal dot-dirs kept ---
setup_fixture
run_with_npm_stub 0
NPX="$AGENT_HOME/.npm/_npx/e46929201c1128dd/node_modules"
mkdir -p "$NPX/gitnexus" "$NPX/.gitnexus-P2oInPLH" "$NPX/.bin" \
         "$NPX/@scope/.pkg-AbCdEf12" "$NPX/.fresh-XYZ" "$NPX/gitnexus/.inner-dot"
echo x > "$NPX/.gitnexus-P2oInPLH/leftover"
stale_ts="$(date -u -d '2 days ago' +%Y%m%d%H%M)"
touch -m -t "$stale_ts" "$NPX/.gitnexus-P2oInPLH" "$NPX/@scope/.pkg-AbCdEf12" \
                        "$NPX/gitnexus/.inner-dot"
bash "$SCRIPT" >"$TMP/out5.log" 2>&1
[[ ! -e "$NPX/.gitnexus-P2oInPLH" ]] || { echo "FAIL: stale remnant survived" >&2; cat "$TMP/out5.log" >&2; exit 1; }
[[ ! -e "$NPX/@scope/.pkg-AbCdEf12" ]] || { echo "FAIL: stale scoped remnant survived" >&2; cat "$TMP/out5.log" >&2; exit 1; }
[[ -d "$NPX/gitnexus" ]] || { echo "FAIL: real package deleted" >&2; cat "$TMP/out5.log" >&2; exit 1; }
[[ -d "$NPX/.bin" ]] || { echo "FAIL: .bin deleted" >&2; cat "$TMP/out5.log" >&2; exit 1; }
[[ -d "$NPX/.fresh-XYZ" ]] || { echo "FAIL: fresh (<24h) remnant deleted" >&2; cat "$TMP/out5.log" >&2; exit 1; }
[[ -d "$NPX/gitnexus/.inner-dot" ]] || { echo "FAIL: package-internal dot-dir deleted" >&2; cat "$TMP/out5.log" >&2; exit 1; }
grep -q "removing stale npx swap remnant" "$TMP/out5.log" || { echo "FAIL: remnant removal not logged" >&2; cat "$TMP/out5.log" >&2; exit 1; }

# --- Case 5: lock guard — second concurrent run must noop ---
setup_fixture
run_with_npm_stub 0
# Hold the lock from a background subshell; second invocation should bail.
(
  exec 9>"$AGENT_HOME/.willikins-agent/npm-cache-prune.lock"
  flock 9
  sleep 2
) &
held_pid=$!
sleep 0.3  # give the holder time to grab the lock
bash "$SCRIPT" >"$TMP/out4.log" 2>&1
grep -q "another npm-cache-prune is running" "$TMP/out4.log" || {
    echo "FAIL: lock guard did not block concurrent run" >&2
    cat "$TMP/out4.log" >&2
    wait $held_pid 2>/dev/null || true
    exit 1
}
wait $held_pid 2>/dev/null || true

echo PASS
