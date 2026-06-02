#!/usr/bin/env bash
# lib.sh — shared helpers for hermes-agent-shell installer scripts.
# Source from other scripts:
#     # shellcheck source=/dev/null
#     . /usr/local/lib/hermes-agent-shell/lib.sh

HERMES_AGENT_SHELL_LOG_DIR="${HERMES_AGENT_SHELL_LOG_DIR:-/var/log/cont-init.d}"
HERMES_AGENT_SHELL_STATE_DIR="${HERMES_AGENT_SHELL_STATE_DIR:-/var/lib/hermes-agent-shell}"
HERMES_AGENT_SHELL_MOTD_FILE="${HERMES_AGENT_SHELL_STATE_DIR}/last-reconcile.motd"

hermes_agent_shell_init_dirs() {
    mkdir -p "$HERMES_AGENT_SHELL_LOG_DIR" "$HERMES_AGENT_SHELL_STATE_DIR"
}

hermes_agent_shell_motd_write() {
    hermes_agent_shell_init_dirs
    printf '%s\n' "$*" > "$HERMES_AGENT_SHELL_MOTD_FILE"
}
