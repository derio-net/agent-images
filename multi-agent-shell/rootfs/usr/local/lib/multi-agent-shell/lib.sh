#!/usr/bin/env bash
# lib.sh — shared helpers for multi-agent-shell installer scripts.
# Source from other scripts:
#     # shellcheck source=/dev/null
#     . /usr/local/lib/multi-agent-shell/lib.sh

MULTI_AGENT_SHELL_LOG_DIR="${MULTI_AGENT_SHELL_LOG_DIR:-/var/log/cont-init.d}"
MULTI_AGENT_SHELL_STATE_DIR="${MULTI_AGENT_SHELL_STATE_DIR:-/var/lib/multi-agent-shell}"
MULTI_AGENT_SHELL_MOTD_FILE="${MULTI_AGENT_SHELL_STATE_DIR}/last-reconcile.motd"

multi_agent_shell_init_dirs() {
    mkdir -p "$MULTI_AGENT_SHELL_LOG_DIR" "$MULTI_AGENT_SHELL_STATE_DIR"
}

multi_agent_shell_motd_write() {
    multi_agent_shell_init_dirs
    printf '%s\n' "$*" > "$MULTI_AGENT_SHELL_MOTD_FILE"
}
