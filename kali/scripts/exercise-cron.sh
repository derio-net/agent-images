#!/usr/bin/env bash
# exercise-cron.sh — Generate and send an exercise reminder
# Usage: exercise-cron.sh [desk|standing]
set -euo pipefail

# Source bashrc for env vars (TELEGRAM_BOT_TOKEN, etc.). The PVC-side
# bashrc routinely contains code only valid in an interactive/tmux
# context (e.g. tmux helper functions invoking `[ -n "$TMUX" ]` which
# returns 1 in cron). Disable BOTH errexit and nounset around the
# source so a non-zero command or unbound-var reference in bashrc
# doesn't propagate up and kill the cron run.
set +eu
[[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc"
set -eu

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
