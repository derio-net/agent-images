#!/usr/bin/env bash
# reap-orphan-envs.sh — DELETE orphaned claude remote-control bridge envs.
#
# Invoked by session-manager.sh on each 5-minute tick. Scans the envs files
# written by wrap-claude.py and, for any whose owning PID is gone, calls
# DELETE /v1/environments/bridge/<env_id> against the Anthropic API.
# See docs/findings/2026-04-22-orphan-env-reaper.md for reconnaissance and
# the rationale for Branch B (supervisor-recorded envs files, not pointer
# files written by claude).
set -euo pipefail

AGENT_DIR="${WILLIKINS_AGENT_DIR:-$HOME/.willikins-agent}"
ENVS_DIR="$AGENT_DIR/envs"
LOGFILE="$AGENT_DIR/reap-orphan-envs.log"
AUTH_STATE="$AGENT_DIR/reap-auth-error.state"
AUTH_BACKOFF_SECS=3600
AUTH_FAIL_THRESHOLD=3
API_BASE="${CLAUDE_API_BASE:-https://api.anthropic.com}"
ANTHROPIC_BETA="environments-2025-11-01"

# Phase 0 findings: bearer is at .claudeAiOauth.accessToken in
# ~/.claude/.credentials.json; org UUID is at .oauthAccount.organizationUuid
# in ~/.claude.json (NOT ~/.claude/config.json).
BEARER_PATH="$HOME/.claude/.credentials.json"
BEARER_KEY=".claudeAiOauth.accessToken // empty"
ORG_UUID_PATH="$HOME/.claude.json"
ORG_UUID_KEY=".oauthAccount.organizationUuid // empty"

mkdir -p "$AGENT_DIR"

log() {
  local msg="[$(date -u '+%Y-%m-%d %H:%M:%S')] [reap] $*"
  echo "$msg" >&2
  echo "$msg" >> "$LOGFILE" 2>/dev/null || true
}

# Serialise overlapping ticks. supercronic fires every 5min; if a tick is slow
# (large queue, 5xx waits, or post-I-4 timeouts), the next tick can stomp
# into the same envs files. The Anthropic API is idempotent so this never
# corrupts state, but it doubles "[reap]" log lines and DELETE counts which
# muddies the Phase 2 soak's accounting. Non-blocking lock — a contended
# tick exits cleanly and the next tick picks up.
LOCKFILE="$AGENT_DIR/reap.lock"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  log "another reaper tick in flight; skipping"
  exit 0
fi

# Surface credential-format drift early. The reaper resolves creds lazily
# (only when at least one orphan exists), which means a missing file would
# otherwise stay invisible until the first orphan turns up — possibly weeks.
[[ -f "$BEARER_PATH" ]] || log "[warn] $BEARER_PATH missing — reaper will fail on first orphan"
[[ -f "$ORG_UUID_PATH" ]] || log "[warn] $ORG_UUID_PATH missing — reaper will fail on first orphan"

if [[ -f "$AUTH_STATE" ]]; then
  last_err=$(awk '{print $1}' "$AUTH_STATE" 2>/dev/null || echo 0)
  fail_count=$(awk '{print $2}' "$AUTH_STATE" 2>/dev/null || echo 0)
  if (( fail_count >= AUTH_FAIL_THRESHOLD )); then
    now=$(date +%s)
    if (( now - last_err < AUTH_BACKOFF_SECS )); then
      log "auth-backoff active (${fail_count} recent failures); skipping"
      exit 0
    fi
  fi
fi

shopt -s nullglob
envs_files=( "$ENVS_DIR"/*.json )

if (( ${#envs_files[@]} == 0 )); then
  exit 0
fi

bearer=""; org_uuid=""
read_creds() {
  if [[ ! -f "$BEARER_PATH" ]]; then
    log "error: $BEARER_PATH missing"; return 1
  fi
  bearer=$(jq -r "$BEARER_KEY" "$BEARER_PATH" 2>/dev/null || true)
  if [[ -z "$bearer" || "$bearer" == "null" ]]; then
    log "error: empty bearer at $BEARER_PATH key=$BEARER_KEY (creds-format drift?)"
    return 1
  fi
  if [[ ! -f "$ORG_UUID_PATH" ]]; then
    log "error: $ORG_UUID_PATH missing"; return 1
  fi
  org_uuid=$(jq -r "$ORG_UUID_KEY" "$ORG_UUID_PATH" 2>/dev/null || true)
  if [[ -z "$org_uuid" || "$org_uuid" == "null" ]]; then
    log "error: empty org UUID at $ORG_UUID_PATH key=$ORG_UUID_KEY"
    return 1
  fi
  return 0
}

auth_error=0
reaped=0

for envfile in "${envs_files[@]}"; do
  env_id=$(jq -r '.env_id // empty' "$envfile" 2>/dev/null || true)
  pid=$(jq -r '.pid // empty' "$envfile" 2>/dev/null || true)
  if [[ -z "$env_id" ]]; then
    log "skip: no env_id in $envfile"
    continue
  fi
  if [[ -n "$pid" && "$pid" =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null; then
    continue
  fi

  if [[ -z "$bearer" ]]; then
    read_creds || { log "aborting — credentials unresolved"; exit 0; }
  fi

  log "DELETE $env_id (file=$envfile pid=${pid:-none})"
  # --max-time / --connect-timeout: a hung TCP connection must not block
  # the entire 5-minute tick. With ~17 baseline phantoms and worst-case
  # 15s per call this caps a stuck reaper at ~4.5 minutes, leaving headroom
  # before the next supercronic tick fires.
  http_code=$(curl -sS --max-time 15 --connect-timeout 5 \
    -o /dev/null -w '%{http_code}' -X DELETE \
    -H "Authorization: Bearer $bearer" \
    -H "x-organization-uuid: $org_uuid" \
    -H "anthropic-beta: $ANTHROPIC_BETA" \
    "$API_BASE/v1/environments/bridge/$env_id" || echo "000")

  case "$http_code" in
    2*|404)
      log "reaped $env_id (HTTP $http_code)"
      rm -f "$envfile"
      reaped=$((reaped+1))
      ;;
    401|403)
      log "auth-error $env_id (HTTP $http_code) — leaving file"
      auth_error=1
      ;;
    5*)
      log "transient $env_id (HTTP $http_code) — leaving file"
      ;;
    *)
      log "unexpected $env_id (HTTP $http_code) — leaving file"
      ;;
  esac
done

if (( auth_error == 1 )); then
  now=$(date +%s)
  prev=0
  [[ -f "$AUTH_STATE" ]] && prev=$(awk '{print $2}' "$AUTH_STATE" 2>/dev/null || echo 0)
  echo "$now $((prev+1))" > "$AUTH_STATE"
else
  rm -f "$AUTH_STATE"
fi

(( reaped > 0 )) && log "reaped $reaped orphan env(s)"
exit 0
