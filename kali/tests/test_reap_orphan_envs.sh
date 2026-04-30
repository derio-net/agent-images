#!/usr/bin/env bash
# test_reap_orphan_envs.sh — harness for scripts/reap-orphan-envs.sh
# Branch B: scans $WILLIKINS_AGENT_DIR/envs/*.json (written by wrap-claude.py),
# not pointer files under ~/.claude/projects.
set -euo pipefail

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP"
export WILLIKINS_AGENT_DIR="$TMP/.willikins-agent"
ENVS_DIR="$WILLIKINS_AGENT_DIR/envs"
mkdir -p "$ENVS_DIR" "$HOME/.claude"

# Fake credentials at the real Phase 0 paths.
cat > "$HOME/.claude/.credentials.json" <<'EOF'
{"claudeAiOauth":{"accessToken":"sk-ant-test-bearer","expiresAt":0}}
EOF
cat > "$HOME/.claude.json" <<'EOF'
{"oauthAccount":{"organizationUuid":"org-uuid-test-000"}}
EOF

# Envs file for a dead-PID env (PID 999999 — almost certainly dead).
cat > "$ENVS_DIR/dead.json" <<'EOF'
{"env_id":"env_orphan_A","pid":999999,"started_at":"2026-04-22T00:00:00Z"}
EOF

# Envs file for a live env — bind to our own test PID so kill -0 succeeds.
printf '{"env_id":"env_live_B","pid":%d,"started_at":"2026-04-22T00:00:00Z"}\n' "$$" \
  > "$ENVS_DIR/live.json"

# Stub curl on PATH.
STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/curl" <<'EOF'
#!/usr/bin/env bash
# Record args + emit canned HTTP code via -w. Honor -o /dev/null.
echo "curl $*" >> "$CURL_LOG"
code="${CURL_STUB_CODE:-200}"
out=""
# Emulate curl's -w '%{http_code}' (the only formatter the reaper uses).
while [[ $# -gt 0 ]]; do
  case "$1" in
    -w) out="$2"; shift 2 ;;
    -o) shift 2 ;;
    *) shift ;;
  esac
done
if [[ "$out" == "%{http_code}" ]]; then
  printf '%s' "$code"
fi
# Match curl exit semantics loosely: 0 unless we want to simulate transport
# failure (which the reaper handles via the "000" branch when curl exits >0).
exit 0
EOF
chmod +x "$STUB_DIR/curl"
export PATH="$STUB_DIR:$PATH"
export CURL_LOG="$TMP/curl.log"

REAPER="$(cd "$(dirname "$0")/.." && pwd)/scripts/reap-orphan-envs.sh"

run_reaper() { CURL_STUB_CODE="$1" bash "$REAPER"; }

# --- Test 1: happy path (dead reaped, live untouched) ---
: > "$CURL_LOG"
run_reaper 200

grep -q "env_orphan_A" "$CURL_LOG" || { echo "FAIL: no DELETE for env_orphan_A"; exit 1; }
if grep -q "env_live_B" "$CURL_LOG"; then echo "FAIL: DELETE called for live env_live_B"; exit 1; fi
[[ -f "$ENVS_DIR/dead.json" ]] && { echo "FAIL: dead envs file not removed"; exit 1; } || true
[[ -f "$ENVS_DIR/live.json" ]] || { echo "FAIL: live envs file wrongly removed"; exit 1; }

# --- Test 2: 404 treated as success, file removed ---
cat > "$ENVS_DIR/dead.json" <<'EOF'
{"env_id":"env_orphan_A2","pid":999999,"started_at":"2026-04-22T00:00:00Z"}
EOF
: > "$CURL_LOG"
run_reaper 404
[[ -f "$ENVS_DIR/dead.json" ]] && { echo "FAIL: file not removed on 404"; exit 1; } || true

# --- Test 3: 401 treated as auth-error, file left in place ---
cat > "$ENVS_DIR/dead.json" <<'EOF'
{"env_id":"env_orphan_A3","pid":999999,"started_at":"2026-04-22T00:00:00Z"}
EOF
: > "$CURL_LOG"
run_reaper 401
[[ -f "$ENVS_DIR/dead.json" ]] || { echo "FAIL: file removed despite 401"; exit 1; }

# --- Test 4: 5xx treated as transient, file left in place ---
cat > "$ENVS_DIR/dead.json" <<'EOF'
{"env_id":"env_orphan_A4","pid":999999,"started_at":"2026-04-22T00:00:00Z"}
EOF
: > "$CURL_LOG"
run_reaper 503
[[ -f "$ENVS_DIR/dead.json" ]] || { echo "FAIL: file removed despite 5xx"; exit 1; }

# --- Test 5: anthropic-beta header is sent ---
cat > "$ENVS_DIR/dead.json" <<'EOF'
{"env_id":"env_orphan_A5","pid":999999,"started_at":"2026-04-22T00:00:00Z"}
EOF
: > "$CURL_LOG"
run_reaper 200
grep -q "anthropic-beta: environments-2025-11-01" "$CURL_LOG" \
  || { echo "FAIL: anthropic-beta header missing"; exit 1; }

echo "OK"
