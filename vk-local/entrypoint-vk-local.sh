#!/bin/sh
# entrypoint-vk-local.sh — Run shared first-boot scripts, then exec vibe-kanban.
# vibe-kanban remains the driver process under tini's PID 1; K8s supervises.
# Runs as USER claude (non-root); all /opt/agent-init.d/* scripts must be
# non-root-safe (they create user dirs under $HOME, not system paths).
set -e

# shopt -s nullglob suppresses literal-glob expansion in bash when the
# directory is empty. The || true makes it a no-op in POSIX sh (where shopt
# is unavailable); the [ -x ] guard below is the real safety net in both cases.
shopt -s nullglob 2>/dev/null || true
for s in /opt/agent-init.d/*; do
    [ -x "$s" ] && "$s"
done

exec /usr/local/bin/vibe-kanban "$@"
