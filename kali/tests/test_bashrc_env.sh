#!/usr/bin/env bash
# test_bashrc_env.sh — harness for kali/config-templates/bashrc.
#
# Verifies that a fresh non-login shell sourcing the bashrc template reads
# secrets from the s6-overlay envdir at /run/s6/basedir/env/ (not
# /proc/1/environ). Runs against a temp envdir so it doesn't depend on a
# live s6-overlay install or real pod secrets.
#
# Reports lengths and sha256 only — never plaintext values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASHRC="$SCRIPT_DIR/config-templates/bashrc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Mirror the live envdir layout into a fixture and rewrite the bashrc to
# point at it. The bashrc references /run/s6/basedir/env/ in exactly one
# place (`_env_from_s6`).
FIXTURE_ENVDIR="$TMP/envdir"
mkdir -p "$FIXTURE_ENVDIR"
sed "s|/run/s6/basedir/env|$FIXTURE_ENVDIR|g" "$BASHRC" > "$TMP/bashrc"

# s6-overlay writes a trailing newline after the value. Mimic that so the
# test exercises the same `$(< file)` newline-stripping the live shell does.
printf 'fake-github-token-value\n' > "$FIXTURE_ENVDIR/GITHUB_TOKEN"
printf 'fake-telegram-bot-token\n' > "$FIXTURE_ENVDIR/TELEGRAM_BOT_TOKEN"
printf '12345\n'                    > "$FIXTURE_ENVDIR/TELEGRAM_CHAT_ID"
printf 'fake-grafana-key\n'         > "$FIXTURE_ENVDIR/GRAFANA_API_KEY"
printf 'fake-grafana-editor\n'      > "$FIXTURE_ENVDIR/GRAFANA_API_EDITOR_KEY"

cat > "$TMP/runner.sh" <<'RUNNER'
#!/usr/bin/env bash
set -euo pipefail
# shellcheck disable=SC1090
. "$1"
emit() {
    local name="$1" val
    val="${!name-}"
    printf '%s_LEN=%d\n' "$name" "${#val}"
    printf '%s_SHA=%s\n' "$name" "$(printf '%s' "$val" | sha256sum | cut -d' ' -f1)"
}
emit GITHUB_TOKEN
emit TELEGRAM_BOT_TOKEN
emit TELEGRAM_CHAT_ID
emit GRAFANA_API_KEY
emit GRAFANA_API_EDITOR_KEY
printf 'WILLIKINS_REPOS=%s\n' "$WILLIKINS_REPOS"
printf 'PUSHGATEWAY_URL=%s\n' "$PUSHGATEWAY_URL"
case ":$PATH:" in
    *":$HOME/.local/bin:"*) printf 'PATH_HAS_LOCAL_BIN=yes\n' ;;
    *)                      printf 'PATH_HAS_LOCAL_BIN=no\n'  ;;
esac
RUNNER

# `env -i` strips every var, including the ones the bashrc tries to honor
# via ${VAR:-…}. That's the strictest form of "fresh shell" — proves the
# envdir is the actual source on a cold start.
OUT="$(env -i HOME="$TMP" PATH=/usr/bin:/bin bash "$TMP/runner.sh" "$TMP/bashrc")"

expect() {
    local label="$1" expected="$2"
    if ! grep -qx "$label=$expected" <<< "$OUT"; then
        printf 'FAIL: %s\n  expected: %s\n  got:\n%s\n' "$label" "$expected" "$OUT" >&2
        exit 1
    fi
}

sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

# Each fixture file ends with \n; `$(< file)` strips exactly one newline.
expect GITHUB_TOKEN_LEN 23
expect GITHUB_TOKEN_SHA "$(sha 'fake-github-token-value')"
expect TELEGRAM_BOT_TOKEN_LEN 23
expect TELEGRAM_BOT_TOKEN_SHA "$(sha 'fake-telegram-bot-token')"
expect TELEGRAM_CHAT_ID_LEN 5
expect TELEGRAM_CHAT_ID_SHA "$(sha '12345')"
expect GRAFANA_API_KEY_LEN 16
expect GRAFANA_API_KEY_SHA "$(sha 'fake-grafana-key')"
expect GRAFANA_API_EDITOR_KEY_LEN 19
expect GRAFANA_API_EDITOR_KEY_SHA "$(sha 'fake-grafana-editor')"

expect WILLIKINS_REPOS "$TMP/repos/willikins:willikins"
expect PUSHGATEWAY_URL 'http://pushgateway.monitoring.svc.cluster.local:9091'
expect PATH_HAS_LOCAL_BIN yes

# Negative test: no executable line in bashrc still reads /proc/1/environ.
# Comments are allowed (the historical context is useful).
if grep -nE '^[^#]*\b/proc/1/environ' "$BASHRC"; then
    printf 'FAIL: bashrc has an executable reference to /proc/1/environ\n' >&2
    exit 1
fi

echo "PASS: bashrc loads all secrets from the s6-overlay envdir (lengths + SHA verified)."
