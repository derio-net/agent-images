#!/usr/bin/env bash
# lib.sh — shared helpers for ruflo-shell installer scripts.
# Source from other scripts:
#     # shellcheck source=/dev/null
#     . /usr/local/lib/ruflo-shell/lib.sh

RUFLO_SHELL_LOG_DIR="${RUFLO_SHELL_LOG_DIR:-/var/log/cont-init.d}"
RUFLO_SHELL_STATE_DIR="${RUFLO_SHELL_STATE_DIR:-/var/lib/ruflo-shell}"
RUFLO_SHELL_MOTD_FILE="${RUFLO_SHELL_STATE_DIR}/last-reconcile.motd"

ruflo_shell_init_dirs() {
    mkdir -p "$RUFLO_SHELL_LOG_DIR" "$RUFLO_SHELL_STATE_DIR"
}

ruflo_shell_motd_write() {
    ruflo_shell_init_dirs
    printf '%s\n' "$*" > "$RUFLO_SHELL_MOTD_FILE"
}
