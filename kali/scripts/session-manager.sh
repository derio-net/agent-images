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
  # `exec` replaces the bash wrapper in place, so $! below is claude's own
  # PID — required for SIGTERM to reach the bridge:shutdown handler that
  # calls DELETE /v1/environments/bridge/<env_id>. Using a process-
  # substitution stdin avoids a pipeline (which would again fork).
  nohup bash -c "exec claude remote-control --name '$SESSION_NAME' < <(echo y)" \
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
