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
  # $1=name $2=path (relative to $HOME) $3=login-command hint (default "$1 login")
  hint="${3:-$1 login}"
  if [ -e "$HOME/$2" ]; then
    # stat may fail on an unreadable/dangling target; degrade to "?" rather
    # than emit a shell arithmetic error on login.
    mtime=$(stat -c %Y "$HOME/$2" 2>/dev/null)
    if [ -n "$mtime" ]; then
      age_days=$(( ( $(date +%s) - mtime ) / 86400 ))
      printf '  ✓ %-9s (~/%s, age %sd)\n' "$1" "$2" "$age_days"
    else
      printf '  ✓ %-9s (~/%s, age ?)\n' "$1" "$2"
    fi
  else
    printf '  ✗ %-9s not logged in — run: %s\n' "$1" "$hint"
  fi
}

# agy (antigravity) auth is interactive on first run of `agy` (no `agy login`),
# and its credential lands at ~/.gemini/antigravity-cli/credentials.enc
# (best-effort path — confirmed post-merge per the spec's Test Plan).
check claude   .claude/credentials.json
check codex    .config/codex/auth.json
check agy      .gemini/antigravity-cli/credentials.enc   agy
check opencode .local/share/opencode/auth.json           "opencode auth login"
