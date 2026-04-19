#!/usr/bin/env bash
# rotate-logs.sh — invoke logrotate against willikins-agent log dir
set -euo pipefail

CONF="/opt/scripts/logrotate.conf"
STATE="/home/claude/.willikins-agent/logrotate.state"

# logrotate lives in /usr/sbin on Debian/Kali, which is not in the supercronic
# PATH (see crontab.txt). Extend locally so `command -v` finds it without
# broadening sbin exposure for other cron jobs.
export PATH="$PATH:/usr/sbin"

if ! command -v logrotate >/dev/null 2>&1; then
  echo "logrotate not installed — skipping" >&2
  exit 0
fi

# Ensure the state dir exists — first cron fire may run before any other
# script has created ~/.willikins-agent.
mkdir -p "$(dirname "$STATE")"

logrotate --state "$STATE" "$CONF"
