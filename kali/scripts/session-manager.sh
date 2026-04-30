#!/usr/bin/env bash
# session-manager.sh — Ensure Claude Code remote-control sessions are running
# Reads WILLIKINS_REPOS env var (colon-separated path:name pairs)
# Example: WILLIKINS_REPOS="$HOME/repos/willikins:willikins:$HOME/repos/frank:frank"

set -euo pipefail

# Source bashrc for env vars (WILLIKINS_REPOS, GITHUB_TOKEN, etc.)
# Needed when invoked by supercronic which doesn't load login shell.
# The PVC-side bashrc routinely contains code that's only valid in an
# interactive/tmux context (e.g. tmux helper functions invoking
# `[ -n "$TMUX" ]` which returns 1 in cron). Disable BOTH errexit
# and nounset around the source so a non-zero command or unbound-var
# reference in bashrc doesn't propagate up and kill the cron run.
set +eu
[[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc"
set -eu

LOGFILE="${HOME}/.willikins-agent/session-manager.log"
PIDDIR="${HOME}/.willikins-agent/pids"
SHUTDOWN_MARKER="/tmp/willikins-shutting-down"
mkdir -p "$(dirname "$LOGFILE")" "$PIDDIR"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOGFILE"; }

# Bail out during pod shutdown (marker written by cont-finish.d/01-shutdown).
# Prevents a supercronic tick racing in after s6 has started draining.
if [[ -f "$SHUTDOWN_MARKER" ]]; then
  log "Shutdown in progress — skipping session check"; exit 0
fi

# Reap any orphaned bridge envs before spawning new sessions. Non-fatal —
# the reaper exits 0 on any expected error path; only catastrophic shell
# failures would propagate here, in which case continuing is still the
# right choice (a missed reap tick is recovered next cycle).
if [[ "${REAP_ORPHAN_ENVS:-1}" == "1" ]]; then
  "$(dirname "$0")/reap-orphan-envs.sh" 2>/dev/null \
    || log "[warn] reap-orphan-envs returned non-zero"
fi

if [[ -z "${WILLIKINS_REPOS:-}" ]]; then
  log "ERROR: WILLIKINS_REPOS not set"; exit 1
fi

IFS=':' read -ra ENTRIES <<< "$WILLIKINS_REPOS"
for ((i=0; i<${#ENTRIES[@]}; i+=2)); do
  REPO_PATH="${ENTRIES[$i]}"
  SESSION_NAME="${ENTRIES[$((i+1))]}"
  PIDFILE="$PIDDIR/${SESSION_NAME}.pid"

  if [[ -f "$PIDFILE" ]]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
      log "Session '$SESSION_NAME' already running (PID $PID)"; continue
    else
      log "Session '$SESSION_NAME' stale PID $PID — restarting"; rm -f "$PIDFILE"
    fi
  fi

  if [[ ! -d "$REPO_PATH/.git" ]]; then
    log "ERROR: $REPO_PATH is not a git repo — skipping '$SESSION_NAME'"; continue
  fi

  log "Starting session '$SESSION_NAME' in $REPO_PATH"
  cd "$REPO_PATH"
  # Spawn through wrap-claude.py: the supervisor scrapes the bridge env_id
  # from claude's stderr and writes ~/.willikins-agent/envs/<session>.json
  # so reap-orphan-envs.sh can DELETE the env when claude dies without
  # running its own bridge:shutdown handler (OOMKill, stdin-close cascade,
  # etc.). On graceful SIGTERM the wrapper forwards the signal and unlinks
  # the file after a clean exit. The `exec` replaces the bash wrapper in
  # place, so $! below is the python supervisor's PID.
  nohup bash -c "exec python3 -u /opt/scripts/wrap-claude.py '$SESSION_NAME' < <(echo y)" \
    >> "${HOME}/.willikins-agent/session-${SESSION_NAME}.log" 2>&1 &
  echo $! > "$PIDFILE"
  log "Session '$SESSION_NAME' started (PID $!)"
  cd - > /dev/null
done

log "Session check complete."

# Push heartbeat metric (non-fatal)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/push-heartbeat.sh" session_manager 2>/dev/null \
  || log "WARN: Heartbeat push failed (Pushgateway may be unavailable)"
