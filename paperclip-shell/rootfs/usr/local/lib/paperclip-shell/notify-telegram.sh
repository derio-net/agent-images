#!/usr/bin/env bash
# notify-telegram.sh — Send a Telegram alert. Fail-silent if env is missing.
# Usage: notify-telegram.sh "title" "detail body"
#
# Reads FRANK_C2_TELEGRAM_BOT_TOKEN + FRANK_C2_TELEGRAM_CHAT_ID from env
# (mounted from the same Infisical-backed Secret used by Grafana/ArgoCD).
set -uo pipefail

TITLE="${1:-paperclip-shell alert}"
DETAIL="${2:-}"

: "${FRANK_C2_TELEGRAM_BOT_TOKEN:=}"
: "${FRANK_C2_TELEGRAM_CHAT_ID:=}"
if [[ -z "$FRANK_C2_TELEGRAM_BOT_TOKEN" || -z "$FRANK_C2_TELEGRAM_CHAT_ID" ]]; then
    # Fail-silent: missing creds is not an installer-blocking condition.
    exit 0
fi

POD="${HOSTNAME:-paperclip-shell}"
# `printf` (no trailing %s\n) avoids the trailing-blank-line that a HEREDOC
# leaves in the urlencoded body — Telegram renders the extra blank line in chat.
TEXT=$(printf '%s\n\n%s\n\nPod: %s\nLogs: kubectl logs %s -c paperclip-shell' \
    "$TITLE" "$DETAIL" "$POD" "$POD")

curl -fsS --max-time 10 \
    -X POST "https://api.telegram.org/bot${FRANK_C2_TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${FRANK_C2_TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${TEXT}" >/dev/null || true
