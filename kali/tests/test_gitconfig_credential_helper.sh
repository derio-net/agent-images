#!/usr/bin/env bash
# test_gitconfig_credential_helper.sh — harness for kali/config-templates/gitconfig.
#
# The credential helper is the only path that runs in non-interactive
# subprocesses (VS Code git, supercronic cron jobs) where ~/.bashrc is not
# sourced. It must read GITHUB_TOKEN from the s6-overlay envdir directly
# and emit the git credential protocol shape:
#     username=<value>
#     password=<value>
#
# Critically, the helper must NOT include the trailing newline that s6
# writes to envdir files. A `password=<token>\n` line followed by the
# extra envdir newline produces `password=<token>` and `password=` (empty)
# — git takes the last-seen value, breaks auth.
#
# Reports lengths and sha256 only — never plaintext values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITCONFIG="$SCRIPT_DIR/config-templates/gitconfig"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FIXTURE_ENVDIR="$TMP/envdir"
mkdir -p "$FIXTURE_ENVDIR"

# Token with shell-metachar bytes (=, ", $) plus a trailing newline matching
# what s6 actually writes. NOT a newline embedded in the value — git's
# credential protocol uses newline as a key/value terminator and rejects
# embedded newlines, so we don't simulate that case.
printf 'tok=value "with" $meta\n' > "$FIXTURE_ENVDIR/GITHUB_TOKEN"

# Materialize the gitconfig with the envdir path rewritten.
sed "s|/run/s6/basedir/env|$FIXTURE_ENVDIR|g" "$GITCONFIG" > "$TMP/gitconfig"

# Extract and execute the helper directly. We don't shell out to git here
# because CI may not have git's credential subsystem reachable; we exercise
# the shell function git would invoke.
HELPER="$(git config --file "$TMP/gitconfig" credential.helper)"
case "$HELPER" in
    !*) HELPER="${HELPER#!}" ;;
    *) printf 'FAIL: helper does not start with "!" (got %q)\n' "$HELPER" >&2; exit 1 ;;
esac

OUT="$(env -i HOME="$TMP" PATH=/usr/bin:/bin bash -c "$HELPER")"

# Expected wire format:
#   username=clawdia-ai-assistant
#   password=tok=value "with" $meta
expected_username="username=clawdia-ai-assistant"
expected_password='password=tok=value "with" $meta'

USERNAME_LINE="$(grep '^username=' <<< "$OUT" || true)"
PASSWORD_LINE="$(grep '^password=' <<< "$OUT" || true)"

if [ "$USERNAME_LINE" != "$expected_username" ]; then
    printf 'FAIL: username line mismatch\n  expected: %s\n  got:      %s\n' "$expected_username" "$USERNAME_LINE" >&2
    exit 1
fi

# Compare via SHA so a regression doesn't echo the (potentially secret) value.
got_pw_sha="$(printf '%s' "$PASSWORD_LINE" | sha256sum | cut -d' ' -f1)"
exp_pw_sha="$(printf '%s' "$expected_password" | sha256sum | cut -d' ' -f1)"
if [ "$got_pw_sha" != "$exp_pw_sha" ]; then
    printf 'FAIL: password line sha mismatch\n  expected_sha: %s (len=%d)\n  got_sha:      %s (len=%d)\n' \
        "$exp_pw_sha" "${#expected_password}" "$got_pw_sha" "${#PASSWORD_LINE}" >&2
    exit 1
fi

# The helper must emit exactly two non-empty lines (username + password).
# A naive `cat /run/s6/...` would smuggle the envdir's trailing newline into
# the password value, producing a third empty line that breaks git's parser.
# Capture into a file so we see real terminator structure (command
# substitution would otherwise strip trailing newlines).
env -i HOME="$TMP" PATH=/usr/bin:/bin bash -c "$HELPER" > "$TMP/helper-out"
TOTAL_LINES="$(wc -l < "$TMP/helper-out")"
NONEMPTY_LINES="$(grep -c . "$TMP/helper-out" || true)"
if [ "$TOTAL_LINES" -ne 2 ] || [ "$NONEMPTY_LINES" -ne 2 ]; then
    printf 'FAIL: expected 2 newline-terminated non-empty lines, got total=%d nonempty=%d\n' \
        "$TOTAL_LINES" "$NONEMPTY_LINES" >&2
    exit 1
fi

# Negative test: gitconfig must not still mention /proc/1/environ.
if grep -q '/proc/1/environ' "$GITCONFIG"; then
    printf 'FAIL: gitconfig still references /proc/1/environ\n' >&2
    exit 1
fi

echo "PASS: gitconfig credential helper emits well-formed wire output, no trailing-newline leak."
