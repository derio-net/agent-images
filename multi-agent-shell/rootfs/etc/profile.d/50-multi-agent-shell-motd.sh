#!/bin/sh
# multi-agent-shell auth-status MOTD — printed on SSH login.
# Presence-only check on each harness's credential file
# (declared in the image's harness manifest, multi-agent-shell/README.md).
#
# Per the multi-harness standard: the detector does NOT validate the
# credential; rotation/expiry is the operator's concern. A printed ✓ means
# only that the file exists.

echo "Harness auth status:"

check() {
  # $1=name $2=path (relative to $HOME)
  if [ -e "$HOME/$2" ]; then
    age_days=$(( ( $(date +%s) - $(stat -c %Y "$HOME/$2") ) / 86400 ))
    echo "  ✓ $1     (~/$2, age ${age_days}d)"
  else
    echo "  ✗ $1     not logged in — run: $1 login"
  fi
}

check claude   .claude/credentials.json
check codex    .config/codex/auth.json
check gemini   .config/gemini/auth.json
check opencode .local/share/opencode/auth.json
