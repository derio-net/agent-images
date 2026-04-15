#!/usr/bin/env bash
# audit-digest.sh — Send daily audit summary via Telegram
# Reads audit.jsonl, summarizes last 24h, sends digest, rotates log

set -euo pipefail

# Source bashrc for env vars (TELEGRAM_BOT_TOKEN, etc.)
[[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUDIT_LOG="/home/claude/.willikins-agent/audit.jsonl"
ARCHIVE_DIR="/home/claude/.willikins-agent/audit-archive"
LOGFILE="/home/claude/.willikins-agent/audit-digest.log"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOGFILE"; }

if [[ ! -f "$AUDIT_LOG" ]]; then
  log "No audit log found — nothing to digest"
  # Still push heartbeat so the alert knows we ran successfully
  "$SCRIPT_DIR/push-heartbeat.sh" audit_digest 2>/dev/null \
    || log "WARN: Heartbeat push failed (Pushgateway may be unavailable)"
  exit 0
fi

TOTAL=$(wc -l < "$AUDIT_LOG" | tr -d ' ')
GIT_PUSHES=$(grep -c '"git push"' "$AUDIT_LOG" 2>/dev/null || echo 0)
FAILURES=$(grep -c '"exit_code": [^0]' "$AUDIT_LOG" 2>/dev/null || echo 0)
SESSIONS=$(python3 -c "
import json, sys
sessions = set()
for line in open('$AUDIT_LOG'):
    try:
        sessions.add(json.loads(line).get('session','?'))
    except: pass
print(len(sessions))
" 2>/dev/null || echo "?")

DIGEST="📊 *Willikins Audit Digest*
$(date -u '+%Y-%m-%d')

• Commands logged: $TOTAL
• Unique sessions: $SESSIONS
• Git pushes: $GIT_PUSHES
• Non-zero exits: $FAILURES"

"$SCRIPT_DIR/notify-telegram.sh" "$DIGEST" || { log "ERROR: Telegram failed"; exit 1; }

# Rotate: archive and truncate
mkdir -p "$ARCHIVE_DIR"
cp "$AUDIT_LOG" "$ARCHIVE_DIR/audit-$(date -u '+%Y%m%d').jsonl"
: > "$AUDIT_LOG"

log "Digest sent: $TOTAL commands, $GIT_PUSHES pushes, $FAILURES failures"

# Push heartbeat metric (non-fatal)
"$SCRIPT_DIR/push-heartbeat.sh" audit_digest 2>/dev/null \
  || log "WARN: Heartbeat push failed (Pushgateway may be unavailable)"
