#!/usr/bin/env bash
# lib.sh — shared helpers for paperclip-shell installer scripts.
# Source from other scripts:
#     # shellcheck source=/dev/null
#     . /usr/local/lib/paperclip-shell/lib.sh

PAPERCLIP_SHELL_LOG_DIR="${PAPERCLIP_SHELL_LOG_DIR:-/var/log/cont-init.d}"
PAPERCLIP_SHELL_STATE_DIR="${PAPERCLIP_SHELL_STATE_DIR:-/var/lib/paperclip-shell}"
PAPERCLIP_SHELL_MOTD_FILE="${PAPERCLIP_SHELL_STATE_DIR}/last-reconcile.motd"

paperclip_shell_init_dirs() {
    mkdir -p "$PAPERCLIP_SHELL_LOG_DIR" "$PAPERCLIP_SHELL_STATE_DIR"
}

paperclip_shell_motd_write() {
    paperclip_shell_init_dirs
    printf '%s\n' "$*" > "$PAPERCLIP_SHELL_MOTD_FILE"
}
