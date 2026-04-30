#!/usr/bin/env bash
# shutdown.sh — gracefully terminate willikins-agent remote-control sessions.
#
# Invoked by K8s preStop hook or by an operator during pod drain. Per
# docs/findings/2026-04-18-remote-control-shutdown.md, the `claude` CLI's
# SIGTERM handler calls DELETE /v1/environments/bridge/<env_id>, which is
# how we avoid phantom sessions in claude.ai.
#
# Since silent-reconnect-phantoms Phase 1, session-manager.sh records the
# wrap-claude.py supervisor's PID (not claude's) in each pidfile. The
# supervisor forwards SIGTERM to its claude child's process group, so the
# bridge:shutdown drain still runs end-to-end. If GRACE_SECONDS expires
# we SIGKILL the supervisor; PDEATHSIG (set by the supervisor's preexec)
# then sends SIGTERM to the claude child as the kernel reaps the parent.
# Any envs file the supervisor left behind is cleaned up by
# reap-orphan-envs.sh on the next session-manager tick.
set -euo pipefail

AGENT_DIR="${WILLIKINS_AGENT_DIR:-$HOME/.willikins-agent}"
LOGFILE="$AGENT_DIR/shutdown.log"
PIDDIR="$AGENT_DIR/pids"
GRACE_SECONDS="${SHUTDOWN_GRACE_SECONDS:-30}"

if [[ ! "$GRACE_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "[shutdown] invalid SHUTDOWN_GRACE_SECONDS='$GRACE_SECONDS' — defaulting to 30" >&2
  GRACE_SECONDS=30
fi

mkdir -p "$AGENT_DIR" "$PIDDIR"

log() {
  local msg="[$(date -u '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" >&2
  # Logfile is on a PVC that may be detaching during pod termination;
  # a failed write must never abort the shutdown itself.
  echo "$msg" >> "$LOGFILE" 2>/dev/null || true
}

read_pid() {
  # Prints the PID stored in $1 and returns 0 iff it looks like a positive integer.
  local pidfile="$1" pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  printf '%s' "$pid"
}

shopt -s nullglob
pidfiles=( "$PIDDIR"/*.pid )

if (( ${#pidfiles[@]} == 0 )); then
  log "no PID files present — nothing to shut down"
  exit 0
fi

tracked=()
for pidfile in "${pidfiles[@]}"; do
  name="$(basename "$pidfile" .pid)"
  if ! pid="$(read_pid "$pidfile")"; then
    log "session '$name' has empty or malformed pidfile — removing"
    rm -f "$pidfile"
    continue
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    log "session '$name' PID $pid already dead — cleaning pidfile"
    rm -f "$pidfile"
    continue
  fi

  log "sending SIGTERM to '$name' (PID $pid)"
  if ! kill -TERM "$pid" 2>/dev/null; then
    log "SIGTERM to $pid failed — process may have just exited"
    rm -f "$pidfile"
    continue
  fi
  tracked+=( "$pidfile" )
done

if (( ${#tracked[@]} == 0 )); then
  log "no live sessions needed signalling"
  exit 0
fi

deadline=$(( $(date +%s) + GRACE_SECONDS ))
while (( $(date +%s) < deadline )); do
  alive=0
  for pidfile in "${tracked[@]}"; do
    [[ -f "$pidfile" ]] || continue
    pid="$(read_pid "$pidfile")" || continue
    if kill -0 "$pid" 2>/dev/null; then
      alive=1
      break
    fi
  done
  (( alive == 0 )) && break
  sleep 1
done

for pidfile in "${tracked[@]}"; do
  [[ -f "$pidfile" ]] || continue
  name="$(basename "$pidfile" .pid)"
  pid="$(read_pid "$pidfile")" || { rm -f "$pidfile"; continue; }
  if kill -0 "$pid" 2>/dev/null; then
    log "SIGKILL straggler '$name' (PID $pid) after ${GRACE_SECONDS}s grace"
    kill -KILL "$pid" 2>/dev/null || true
  else
    log "session '$name' (PID $pid) exited gracefully"
  fi
  rm -f "$pidfile"
done

log "shutdown complete"
