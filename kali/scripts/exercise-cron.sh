#!/usr/bin/env bash
# exercise-cron.sh — Generate and send an exercise reminder
# Usage: exercise-cron.sh [desk|standing]
set -euo pipefail

# Source bashrc for env vars (TELEGRAM_BOT_TOKEN, etc.). The PVC-side
# bashrc may reference shell-state vars bound only in interactive/tmux
# sessions (e.g. `_TMUX_LAST_PWD`); disable nounset around the source
# so its missing refs don't kill the cron run.
set +u
[[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc"
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${WILLIKINS_REPO_PATH:-/home/claude/repos/willikins}"
CONTEXT="${1:-desk}"
LOGFILE="/home/claude/.willikins-agent/exercise-cron.log"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOGFILE"; }

log "Generating exercise reminder (context: $CONTEXT)"
REMINDER=$(cd "$REPO_DIR" && claude -p \
  "Use the exercise-reminder skill. Context: $CONTEXT. Time: $(date '+%H:%M'). Generate the reminder message only." \
  2>/dev/null) || { log "ERROR: Claude invocation failed"; exit 1; }

[[ -z "$REMINDER" ]] && { log "ERROR: Empty response"; exit 1; }

log "Sending via Telegram"
"$SCRIPT_DIR/notify-telegram.sh" "$REMINDER" || { log "ERROR: Telegram failed"; exit 1; }
log "Exercise reminder sent"

# Push heartbeat metric (non-fatal -- don't fail the reminder if Pushgateway is down)
"$SCRIPT_DIR/push-heartbeat.sh" exercise_reminder context="$CONTEXT" 2>/dev/null \
  || log "WARN: Heartbeat push failed (Pushgateway may be unavailable)"
