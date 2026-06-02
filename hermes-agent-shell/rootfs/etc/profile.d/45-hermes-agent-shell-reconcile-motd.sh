# 45-hermes-agent-shell-reconcile-motd.sh — Print the last reconcile summary
# on interactive shell login. The s6-overlay sshd is built with UsePAM=no
# (see agent-shell-base sshd_config), so pam_motd does not fire; profile.d is
# the simplest mechanism that still works for both ssh and
# `kubectl exec -it ... bash -l`.
#
# Numbered 45- so it prints BEFORE the 50- auth-status table — per the
# multi-harness-shells spec, the reconcile summary leads and the auth table
# is appended.
#
# Sourced by /etc/profile (interactive login shells) and by ~/.bashrc via
# the default Debian skeleton. Quiet for non-interactive shells.

[ -n "$PS1" ] || return 0

_hermes_agent_shell_motd_file=/var/lib/hermes-agent-shell/last-reconcile.motd
if [ -r "$_hermes_agent_shell_motd_file" ]; then
    cat "$_hermes_agent_shell_motd_file"
fi
unset _hermes_agent_shell_motd_file
