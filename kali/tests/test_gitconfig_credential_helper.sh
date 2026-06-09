#!/usr/bin/env bash
# test_gitconfig_credential_helper.sh — harness for kali/config-templates/gitconfig.
#
# The credential helper is the only path that runs in non-interactive
# subprocesses (VS Code git, supercronic cron jobs) where ~/.bashrc is not
# sourced. It emits the git credential protocol shape:
#     username=x-access-token
#     password=<value>
#
# It PREFERS the mounted GitHub App token at /var/run/github/token (rotated by
# ESO, key never on the pod) and falls back to the s6 envdir token during
# cutover. `x-access-token` is the App-token username convention and is also
# accepted with a classic PAT, so it works for both sources.
#
# Critically, the helper must NOT include the trailing newline that s6 / the
# mounted file write. A `password=<token>\n` line followed by an extra envdir
# newline produces `password=<token>` and `password=` (empty) — git takes the
# last-seen value, breaks auth.
#
# Reports lengths and sha256 only — never plaintext values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GITCONFIG="$SCRIPT_DIR/config-templates/gitconfig"

sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

# Run the helper for one scenario and assert the emitted wire output.
#   $1 label   $2 file-token (empty = no /var/run/github/token)   $3 env-token
#   $4 expected password value the helper should choose
run_scenario() {
    local label="$1" file_token="$2" env_token="$3" expected="$4"
    local tmp; tmp="$(mktemp -d)"
    local file_dir="$tmp/var-run-github" env_dir="$tmp/envdir"
    mkdir -p "$file_dir" "$env_dir"
    [ -n "$file_token" ] && printf '%s\n' "$file_token" > "$file_dir/token"
    printf '%s\n' "$env_token" > "$env_dir/GITHUB_TOKEN"

    # Rewrite BOTH real paths to the fixtures so the test never touches a real
    # /var/run/github/token on the build host.
    local cfg="$tmp/gitconfig"
    sed -e "s|/var/run/github|$file_dir|g" -e "s|/run/s6/basedir/env|$env_dir|g" \
        "$GITCONFIG" > "$cfg"

    local helper; helper="$(git config --file "$cfg" credential.helper)"
    case "$helper" in
        !*) helper="${helper#!}" ;;
        *) printf 'FAIL [%s]: helper does not start with "!" (got %q)\n' "$label" "$helper" >&2; exit 1 ;;
    esac

    local out_file="$tmp/out"
    # Run under /bin/sh (dash), NOT bash — git invokes credential helpers via
    # `sh -c`, so the helper must be POSIX-sh-safe (e.g. $(cat …), not the
    # bash-only $(< …) read which yields an empty password under dash).
    env -i HOME="$tmp" PATH=/usr/bin:/bin sh -c "$helper" > "$out_file"
    local username_line password_line
    username_line="$(grep '^username=' "$out_file" || true)"
    password_line="$(grep '^password=' "$out_file" || true)"

    if [ "$username_line" != "username=x-access-token" ]; then
        printf 'FAIL [%s]: username line mismatch\n  expected: username=x-access-token\n  got:      %s\n' \
            "$label" "$username_line" >&2; exit 1
    fi
    if [ "$(sha "$password_line")" != "$(sha "password=$expected")" ]; then
        printf 'FAIL [%s]: password line sha mismatch (got len=%d)\n' "$label" "${#password_line}" >&2; exit 1
    fi
    # Exactly two newline-terminated non-empty lines — no trailing-newline leak.
    local total nonempty
    total="$(wc -l < "$out_file")"; nonempty="$(grep -c . "$out_file" || true)"
    if [ "$total" -ne 2 ] || [ "$nonempty" -ne 2 ]; then
        printf 'FAIL [%s]: expected 2 non-empty lines, got total=%d nonempty=%d\n' \
            "$label" "$total" "$nonempty" >&2; exit 1
    fi
    rm -rf "$tmp"
    printf 'OK   [%s]\n' "$label"
}

# Prefer the mounted App-token file when present (value differs from the env one
# to prove precedence). Token carries shell-metachar bytes (=, ", $).
run_scenario prefer_file 'file=tok "with" $meta' 'env-token-should-be-ignored' 'file=tok "with" $meta'

# Fall back to the s6 envdir token when the file is absent (cutover / pre-mount).
run_scenario fallback_envdir '' 'env=tok "with" $meta' 'env=tok "with" $meta'

# Negative test: gitconfig must not reference /proc/1/environ.
if grep -q '/proc/1/environ' "$GITCONFIG"; then
    printf 'FAIL: gitconfig still references /proc/1/environ\n' >&2
    exit 1
fi

echo "PASS: gitconfig credential helper prefers the App-token file, falls back to the s6 envdir, emits well-formed wire output."
