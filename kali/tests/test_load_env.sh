#!/usr/bin/env bash
# test_load_env.sh — harness for kali/config-templates/load-env.sh
#
# Verifies that load-env.sh reads the s6-overlay envdir and exports values
# with byte-identical fidelity, including values containing shell
# metacharacters (=, ", $, newline) that an `eval`-based loader would mangle.
#
# Runs against a temp envdir, so it does not depend on a live s6-overlay
# install or the secure-agent-pod's real secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SCRIPT_DIR/config-templates/load-env.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

[ -x "$SCRIPT" ] || chmod +x "$SCRIPT"

# The script hard-codes /run/s6/basedir/env/. To test without root, we copy
# the script into TMP and rewrite the path to a fixture envdir.
FIXTURE_ENVDIR="$TMP/envdir"
mkdir -p "$FIXTURE_ENVDIR"
sed "s|/run/s6/basedir/env|$FIXTURE_ENVDIR|g" "$SCRIPT" > "$TMP/load-env.sh"
chmod +x "$TMP/load-env.sh"

# Fixture 1: simple value.
printf 'simple-value' > "$FIXTURE_ENVDIR/SIMPLE_VAR"

# Fixture 2: value with =, ", $, and an embedded newline. Exactly the shapes
# that break naive `export $(...)` and `eval` loaders.
printf 'a=b "c" $d\nsecond-line' > "$FIXTURE_ENVDIR/COMPLEX_VAR"

# Fixture 3: empty file is allowed and should produce an empty export.
: > "$FIXTURE_ENVDIR/EMPTY_VAR"

# Fixture 4: a stray subdirectory must be skipped, not exported.
mkdir "$FIXTURE_ENVDIR/SHOULD_BE_SKIPPED_DIR"

# Source in a fresh shell and emit lengths + a SHA so we never print the
# (potentially secret) values themselves. Compare against expected hashes.
cat > "$TMP/runner.sh" <<'RUNNER'
#!/usr/bin/env bash
set -euo pipefail
. "$1"
printf 'SIMPLE_VAR_LEN=%d\n' "${#SIMPLE_VAR}"
printf 'SIMPLE_VAR_SHA=%s\n' "$(printf '%s' "$SIMPLE_VAR" | sha256sum | cut -d' ' -f1)"
printf 'COMPLEX_VAR_LEN=%d\n' "${#COMPLEX_VAR}"
printf 'COMPLEX_VAR_SHA=%s\n' "$(printf '%s' "$COMPLEX_VAR" | sha256sum | cut -d' ' -f1)"
printf 'EMPTY_VAR_LEN=%d\n' "${#EMPTY_VAR}"
if [ -n "${SHOULD_BE_SKIPPED_DIR:-}" ]; then
    printf 'STRAY_DIR_EXPORTED=yes\n'
else
    printf 'STRAY_DIR_EXPORTED=no\n'
fi
RUNNER
chmod +x "$TMP/runner.sh"

OUT="$(env -i HOME="$TMP" PATH="$PATH" bash "$TMP/runner.sh" "$TMP/load-env.sh")"

expect() {
    local label="$1" expected="$2"
    if ! grep -qx "$label=$expected" <<< "$OUT"; then
        printf 'FAIL: %s\n  expected: %s\n  got:\n%s\n' "$label" "$expected" "$OUT" >&2
        exit 1
    fi
}

# SIMPLE_VAR: "simple-value" → 12 bytes, sha256 = …
expect SIMPLE_VAR_LEN 12
expect SIMPLE_VAR_SHA "$(printf '%s' 'simple-value' | sha256sum | cut -d' ' -f1)"

# COMPLEX_VAR: 'a=b "c" $d\nsecond-line' → 22 bytes
expect COMPLEX_VAR_LEN 22
expect COMPLEX_VAR_SHA "$(printf '%s' 'a=b "c" $d
second-line' | sha256sum | cut -d' ' -f1)"

expect EMPTY_VAR_LEN 0
expect STRAY_DIR_EXPORTED no

echo "PASS: load-env.sh round-trips all fixture envdir entries (byte-identical)."
