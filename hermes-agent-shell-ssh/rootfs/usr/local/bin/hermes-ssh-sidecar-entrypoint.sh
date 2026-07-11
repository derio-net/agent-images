#!/bin/bash
# Entry point for the hermes-agent-shell SSH sidecar. Idempotent first-boot prep
# (host keys + authorized_keys onto the shared PVC), then exec sshd in the
# foreground so it is PID 1 and the kubelet's TCP probes on 2222 see it directly.
#
# Runs as the agent UID (pod securityContext runAsUser 1000). HOME/AGENT_HOME is
# the shared tool-home PVC at /opt/data/home; host keys persist there across
# restarts (same mechanism as agent-shell-base's 10-ssh-host-keys).
set -euo pipefail

: "${AGENT_HOME:=/opt/data/home}"

KEYDIR="${AGENT_HOME}/.ssh-host-keys"
mkdir -p "$KEYDIR"
chmod 700 "$KEYDIR"
if [ ! -f "$KEYDIR/ssh_host_ed25519_key" ]; then
    echo "[entrypoint] generating SSH host keys (first boot)"
    ssh-keygen -t ed25519 -f "$KEYDIR/ssh_host_ed25519_key" -N ""
    ssh-keygen -t rsa -b 4096 -f "$KEYDIR/ssh_host_rsa_key" -N ""
fi
chmod 600 "$KEYDIR"/ssh_host_*_key

# Authorized keys from the SOPS-managed Secret (mounted read-only at /etc/ssh-keys
# in the sidecar only). Copied onto the PVC so sshd reads a 0600 file it owns.
mkdir -p "${AGENT_HOME}/.ssh"
chmod 700 "${AGENT_HOME}/.ssh"
if [ -f /etc/ssh-keys/authorized_keys ]; then
    install -m 600 /etc/ssh-keys/authorized_keys "${AGENT_HOME}/.ssh/authorized_keys"
fi

exec /usr/sbin/sshd -D -e -f /opt/sshd_config
