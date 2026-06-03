#!/usr/bin/env bash
# lib.sh — shared helpers for infra-shell installer scripts.
# Source from other scripts:
#     # shellcheck source=/dev/null
#     . /usr/local/lib/infra-shell/lib.sh

INFRA_SHELL_LOG_DIR="${INFRA_SHELL_LOG_DIR:-/var/log/cont-init.d}"
INFRA_SHELL_STATE_DIR="${INFRA_SHELL_STATE_DIR:-/var/lib/infra-shell}"
INFRA_SHELL_MOTD_FILE="${INFRA_SHELL_STATE_DIR}/last-reconcile.motd"

infra_shell_init_dirs() {
    mkdir -p "$INFRA_SHELL_LOG_DIR" "$INFRA_SHELL_STATE_DIR"
}

infra_shell_motd_write() {
    infra_shell_init_dirs
    printf '%s\n' "$*" > "$INFRA_SHELL_MOTD_FILE"
}
