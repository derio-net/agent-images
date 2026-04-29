#!/bin/sh
# entrypoint-vk-local.sh — Run shared first-boot scripts, then exec vibe-kanban.
# vibe-kanban remains the driver process under tini's PID 1; K8s supervises.
set -e

shopt -s nullglob 2>/dev/null || true
for s in /opt/agent-init.d/*; do
    [ -x "$s" ] && "$s"
done

exec vibe-kanban "$@"
