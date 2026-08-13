# Put bun's GLOBAL bin directory on PATH for login shells (derio-net/frank#759).
#
# WHY THIS FILE HAS TO EXIST: sshd scrubs the container environment, and in this
# sidecar sshd is PID 1 — OpenSSH overwrites its own argv/environ with the
# process title, so the /proc/1/environ re-export trick used elsewhere in this
# family reads proctitle junk here. A login shell's PATH therefore comes from
# /etc/profile.d or from nowhere at all.
#
# WHY $HOME AND NOT A BAKED PATH: $HOME is /opt/data/home, a Longhorn PVC. The
# runtime ships in the image (/usr/local/bin/bun, already on the default PATH);
# anything the operator installs with `bun install -g` lands in $HOME/.bun/bin
# and survives pod restarts. That persistence is the whole reason the client CLI
# is installed at runtime rather than baked into this public image.
#
# The directory legitimately does not exist before the first global install, so
# this must not fail or complain when it is absent.
#
# NUMBERING: this container's /etc/profile.d holds 35-hermes-agent-shell-byok-env.sh
# (mounted by frank, not baked) and 70-systemd-shell-extra.sh. There is no
# 50-…-motd.sh here — that belongs to the sibling hermes-agent-shell image — so
# the family's "number below the MOTD" rule is about a file this image does not
# contain. 36 sits just after frank's shim and well clear of 70.
#
# Verify with `bash -lc 'command -v <cli>'`. NOT `ssh host -- cmd`, which skips
# /etc/profile.d entirely and proves nothing about this file.

case ":${PATH}:" in
    *":${HOME}/.bun/bin:"*) ;;
    *) PATH="${HOME}/.bun/bin:${PATH}"; export PATH ;;
esac
