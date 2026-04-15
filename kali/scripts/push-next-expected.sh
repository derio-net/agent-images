#!/usr/bin/env bash
# push-next-expected.sh — Push the next expected run timestamp to Pushgateway
# Usage: push-next-expected.sh <job_name> <script_pattern> [label=value ...]
#
# Reads the crontab, finds entries matching <script_pattern>, computes the
# next fire time, and pushes it as willikins_heartbeat_next_expected_timestamp.
#
# Example: push-next-expected.sh exercise_reminder exercise-cron.sh context=desk

set -euo pipefail

JOB="${1:?Usage: push-next-expected.sh <job_name> <script_pattern> [label=value ...]}"
SCRIPT_PATTERN="${2:?Usage: push-next-expected.sh <job_name> <script_pattern> [label=value ...]}"
shift 2

[[ -z "${PUSHGATEWAY_URL:-}" ]] && [[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc"
PUSHGATEWAY_URL="${PUSHGATEWAY_URL:?PUSHGATEWAY_URL must be set}"

VENV_PYTHON="$HOME/.willikins-agent/.venv/bin/python"
COMPUTE="$(dirname "$0")/compute-next-run.py"

NEXT_TS=$("$VENV_PYTHON" "$COMPUTE" "$SCRIPT_PATTERN") || { echo "Failed to compute next run" >&2; exit 1; }

# Build grouping key
GROUPING="job/$JOB"
for LABEL in "$@"; do
  KEY="${LABEL%%=*}"
  VAL="${LABEL##*=}"
  GROUPING="$GROUPING/$KEY/$VAL"
done

cat <<METRICS | curl -s --fail --data-binary @- "${PUSHGATEWAY_URL}/metrics/${GROUPING}"
# TYPE willikins_heartbeat_next_expected_timestamp gauge
# HELP willikins_heartbeat_next_expected_timestamp Unix timestamp of next expected successful run
willikins_heartbeat_next_expected_timestamp $NEXT_TS
METRICS
