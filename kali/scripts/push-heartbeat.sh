#!/usr/bin/env bash
# push-heartbeat.sh -- Push a success heartbeat to Prometheus Pushgateway
# Usage: push-heartbeat.sh <job_name> [label=value ...]
# Example: push-heartbeat.sh exercise_reminder context=desk
#
# Requires: PUSHGATEWAY_URL env var (e.g., http://pushgateway.observability.svc:9091)
# Pushes: willikins_heartbeat_last_success_timestamp gauge with current unix timestamp

set -euo pipefail

JOB="${1:?Usage: push-heartbeat.sh <job_name> [label=value ...]}"
shift

# Source bashrc for PUSHGATEWAY_URL if not already set. The PVC-side
# bashrc routinely contains code only valid in an interactive/tmux
# context (e.g. tmux helper functions invoking `[ -n "$TMUX" ]` which
# returns 1 in cron). Disable BOTH errexit and nounset around the
# source so a non-zero command or unbound-var reference in bashrc
# doesn't propagate up and kill the cron run.
if [[ -z "${PUSHGATEWAY_URL:-}" ]] && [[ -f "$HOME/.bashrc" ]]; then
  set +eu
  source "$HOME/.bashrc"
  set -eu
fi

PUSHGATEWAY_URL="${PUSHGATEWAY_URL:?PUSHGATEWAY_URL must be set}"

# Build label string for grouping key
GROUPING="job/$JOB"
for LABEL in "$@"; do
  KEY="${LABEL%%=*}"
  VAL="${LABEL##*=}"
  GROUPING="$GROUPING/$KEY/$VAL"
done

TIMESTAMP=$(date +%s)

# Push the metric
cat <<METRICS | curl -s --fail --data-binary @- "${PUSHGATEWAY_URL}/metrics/${GROUPING}"
# TYPE willikins_heartbeat_last_success_timestamp gauge
# HELP willikins_heartbeat_last_success_timestamp Unix timestamp of last successful run
willikins_heartbeat_last_success_timestamp $TIMESTAMP
METRICS
