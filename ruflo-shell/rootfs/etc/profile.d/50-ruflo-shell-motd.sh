# 50-ruflo-shell-motd.sh — Print the last reconcile summary on interactive
# shell login. The s6-overlay sshd is built with UsePAM=no (see agent-shell-base
# sshd_config), so pam_motd does not fire; profile.d is the simplest mechanism
# that still works for both ssh and `kubectl exec -it ... bash -l`.
#
# Sourced by /etc/profile (interactive login shells) and by ~/.bashrc via the
# default Debian skeleton. Quiet for non-interactive shells.

[ -n "$PS1" ] || return 0

_ruflo_shell_motd_file=/var/lib/ruflo-shell/last-reconcile.motd
if [ -r "$_ruflo_shell_motd_file" ]; then
    cat "$_ruflo_shell_motd_file"
fi
unset _ruflo_shell_motd_file
