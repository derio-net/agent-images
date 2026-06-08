#!/usr/bin/env bash
# test_bashrc_env.sh — harness for kali/config-templates/bashrc.
#
# Verifies that a fresh non-login shell sourcing the bashrc template:
#   - reads the bulk of its secrets from the s6-overlay envdir at
#     /run/s6/basedir/env/ (not /proc/1/environ), and
#   - resolves GITHUB_TOKEN by PREFERRING the mounted App-token file at
#     /var/run/github/token, falling back to the s6 envdir when absent.
#
# Runs against temp fixtures so it doesn't depend on a live s6-overlay install,
# a real mounted token, or real pod secrets. Reports lengths and sha256 only —
# never plaintext values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASHRC="$SCRIPT_DIR/config-templates/bashrc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

sha() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

FIXTURE_ENVDIR="$TMP/envdir"
FIXTURE_NOFILE="$TMP/no-token-file"   # empty: no /var/run/github/token
FIXTURE_FILE="$TMP/with-token-file"   # holds a token to prove file-preference
mkdir -p "$FIXTURE_ENVDIR" "$FIXTURE_NOFILE" "$FIXTURE_FILE"

# s6-overlay / the mounted secret write a trailing newline; mimic it so the test
# exercises the same `$(< file)` newline-stripping the live shell does.
printf 'fake-github-token-value\n' > "$FIXTURE_ENVDIR/GITHUB_TOKEN"
printf 'fake-telegram-bot-token\n' > "$FIXTURE_ENVDIR/TELEGRAM_BOT_TOKEN"
printf '12345\n'                    > "$FIXTURE_ENVDIR/TELEGRAM_CHAT_ID"
printf 'fake-grafana-key\n'         > "$FIXTURE_ENVDIR/GRAFANA_API_KEY"
printf 'fake-grafana-editor\n'      > "$FIXTURE_ENVDIR/GRAFANA_API_EDITOR_KEY"
printf 'app-installation-token\n'   > "$FIXTURE_FILE/token"

# runner sources a bashrc and emits len/sha for the requested vars.
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

# Materialize a bashrc with both real paths rewritten to fixtures.
#   $1 = dir to substitute for /var/run/github  (token file lives at <dir>/token)
make_bashrc() {
    sed -e "s|/var/run/github|$1|g" -e "s|/run/s6/basedir/env|$FIXTURE_ENVDIR|g" \
        "$BASHRC" > "$TMP/bashrc"
}
run_bashrc() {
    # `env -i` strips every var — strictest "fresh shell" / cold start.
    env -i HOME="$TMP" PATH=/usr/bin:/bin bash "$TMP/runner.sh" "$TMP/bashrc"
}
expect() {
    local out="$1" label="$2" expected="$3"
    if ! grep -qx "$label=$expected" <<< "$out"; then
        printf 'FAIL: %s\n  expected: %s\n  got:\n%s\n' "$label" "$expected" "$out" >&2
        exit 1
    fi
}

# --- Scenario A: no mounted token file → GITHUB_TOKEN falls back to s6 envdir ---
make_bashrc "$FIXTURE_NOFILE"
OUT_A="$(run_bashrc)"
expect "$OUT_A" GITHUB_TOKEN_LEN 23
expect "$OUT_A" GITHUB_TOKEN_SHA "$(sha 'fake-github-token-value')"
# The other secrets always come from the s6 envdir.
expect "$OUT_A" TELEGRAM_BOT_TOKEN_LEN 23
expect "$OUT_A" TELEGRAM_BOT_TOKEN_SHA "$(sha 'fake-telegram-bot-token')"
expect "$OUT_A" TELEGRAM_CHAT_ID_LEN 5
expect "$OUT_A" TELEGRAM_CHAT_ID_SHA "$(sha '12345')"
expect "$OUT_A" GRAFANA_API_KEY_LEN 16
expect "$OUT_A" GRAFANA_API_KEY_SHA "$(sha 'fake-grafana-key')"
expect "$OUT_A" GRAFANA_API_EDITOR_KEY_LEN 19
expect "$OUT_A" GRAFANA_API_EDITOR_KEY_SHA "$(sha 'fake-grafana-editor')"
expect "$OUT_A" WILLIKINS_REPOS "$TMP/repos/willikins:willikins"
expect "$OUT_A" PUSHGATEWAY_URL 'http://pushgateway.monitoring.svc.cluster.local:9091'
expect "$OUT_A" PATH_HAS_LOCAL_BIN yes

# --- Scenario B: mounted token file present → GITHUB_TOKEN PREFERS it ---
make_bashrc "$FIXTURE_FILE"
OUT_B="$(run_bashrc)"
expect "$OUT_B" GITHUB_TOKEN_LEN 22
expect "$OUT_B" GITHUB_TOKEN_SHA "$(sha 'app-installation-token')"

# Negative test: no executable line in bashrc reads /proc/1/environ.
if grep -nE '^[^#]*\b/proc/1/environ' "$BASHRC"; then
    printf 'FAIL: bashrc has an executable reference to /proc/1/environ\n' >&2
    exit 1
fi

echo "PASS: bashrc prefers the mounted App-token file for GITHUB_TOKEN, falls back to the s6 envdir, and loads the other secrets from the envdir."
