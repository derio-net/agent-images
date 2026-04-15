#!/usr/bin/env bash
# notify-telegram.sh — Send a message via Telegram Bot API
# Usage: ./notify-telegram.sh "message text"
# Requires: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables

set -euo pipefail

MESSAGE="${1:?Usage: notify-telegram.sh \"message text\"}"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set" >&2
  exit 1
fi

API_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$API_URL" \
  -d chat_id="$TELEGRAM_CHAT_ID" \
  -d text="$MESSAGE" \
  -d parse_mode="Markdown")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "ERROR: Telegram API returned HTTP $HTTP_CODE" >&2
  echo "$BODY" >&2
  exit 1
fi

echo "Notification sent."
