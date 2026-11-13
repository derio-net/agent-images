#!/usr/bin/env bash
# test_gh_wrapper.sh — harness for base/usr/local/bin/gh.
#
# The wrapper must authenticate `gh` with the CURRENT mounted GitHub App token
# (read fresh per call, since App tokens rotate), and fall through transparently
# to the real gh where no token file is mounted. Uses the wrapper's override
# vars (GH_APP_TOKEN_FILE / GH_REAL_BIN) to point at fixtures.
set -euo pipefail

WRAPPER="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/base/usr/local/bin/gh"
[ -f "$WRAPPER" ] || { echo "FAIL: wrapper not found at $WRAPPER" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# Stub "real gh": echoes the GH_TOKEN it received + its args.
cat > "$TMP/realgh" <<'STUB'
#!/bin/sh
printf 'GH_TOKEN=%s ARGS=%s\n' "${GH_TOKEN:-NONE}" "$*"
STUB
chmod +x "$TMP/realgh"

# Case 1: token file present → wrapper injects its contents as GH_TOKEN.
printf 'ghs_apptoken123' > "$TMP/token"
out="$(GH_APP_TOKEN_FILE="$TMP/token" GH_REAL_BIN="$TMP/realgh" sh "$WRAPPER" api graphql)"
if [ "$out" != "GH_TOKEN=ghs_apptoken123 ARGS=api graphql" ]; then
    printf 'FAIL [token present]: got %q\n' "$out" >&2; exit 1
fi
echo "OK [token present → GH_TOKEN injected from file]"

# Case 2: no token file → fall through to real gh, GH_TOKEN untouched.
out="$(env -u GH_TOKEN GH_APP_TOKEN_FILE="$TMP/absent" GH_REAL_BIN="$TMP/realgh" sh "$WRAPPER" auth status)"
if [ "$out" != "GH_TOKEN=NONE ARGS=auth status" ]; then
    printf 'FAIL [no token file]: got %q\n' "$out" >&2; exit 1
fi
echo "OK [no token file → fall through, GH_TOKEN untouched]"

echo "PASS: gh wrapper injects the current App token when mounted, falls back otherwise."
