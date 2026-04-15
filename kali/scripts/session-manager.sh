#!/usr/bin/env bash
# session-manager.sh — Ensure Claude Code remote-control sessions are running
# Reads WILLIKINS_REPOS env var (colon-separated path:name pairs)
# Example: WILLIKINS_REPOS="/home/claude/repos/willikins:willikins:/home/claude/repos/frank:frank"

set -euo pipefail

# Source bashrc for env vars (WILLIKINS_REPOS, GITHUB_TOKEN, etc.)
# Needed when invoked by supercronic which doesn't load login shell
[[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc"

LOGFILE="/home/claude/.willikins-agent/session-manager.log"
PIDDIR="/home/claude/.willikins-agent/pids"
mkdir -p "$(dirname "$LOGFILE")" "$PIDDIR"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOGFILE"; }

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
  nohup bash -c "echo y | claude remote-control --name '$SESSION_NAME'" \
    >> "/home/claude/.willikins-agent/session-${SESSION_NAME}.log" 2>&1 &
  echo $! > "$PIDFILE"
  log "Session '$SESSION_NAME' started (PID $!)"
  cd - > /dev/null
done

log "Session check complete."

# Push heartbeat metric (non-fatal)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/push-heartbeat.sh" session_manager 2>/dev/null \
  || log "WARN: Heartbeat push failed (Pushgateway may be unavailable)"
