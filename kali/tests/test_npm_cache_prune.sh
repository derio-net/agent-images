#!/usr/bin/env bash
# test_npm_cache_prune.sh — harness for scripts/npm-cache-prune.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export AGENT_HOME="$TMP"
export HOME="$TMP"
mkdir -p "$AGENT_HOME/.npm/_cacache/content-v2"

# Old file (atime 8 days ago) — must be deleted.
old="$AGENT_HOME/.npm/_cacache/content-v2/old.tgz"
echo old > "$old"
touch -a -t "$(date -u -d '8 days ago' +%Y%m%d%H%M)" "$old"

# Fresh file (atime now) — must remain.
fresh="$AGENT_HOME/.npm/_cacache/content-v2/fresh.tgz"
echo fresh > "$fresh"
touch -a "$fresh"

# Stub npm so the script doesn't depend on a real install.
STUB_BIN="$TMP/bin"
mkdir -p "$STUB_BIN"
cat > "$STUB_BIN/npm" <<'EOS'
#!/usr/bin/env bash
echo "npm cache verify (stub) called"
EOS
chmod +x "$STUB_BIN/npm"
export PATH="$STUB_BIN:$PATH"

bash "$SCRIPT_DIR/scripts/npm-cache-prune.sh" >"$TMP/out.log" 2>&1

if [[ -e "$old" ]]; then
    echo "FAIL: old cache file still present" >&2
    cat "$TMP/out.log" >&2
    exit 1
fi
if [[ ! -e "$fresh" ]]; then
    echo "FAIL: fresh cache file was deleted" >&2
    cat "$TMP/out.log" >&2
    exit 1
fi
if ! grep -q "npm cache verify" "$TMP/out.log"; then
    echo "FAIL: npm verify was not invoked" >&2
    cat "$TMP/out.log" >&2
    exit 1
fi

# Absent cache dir — script must exit 0 with a noop message.
rm -rf "$AGENT_HOME/.npm"
bash "$SCRIPT_DIR/scripts/npm-cache-prune.sh" >"$TMP/out2.log" 2>&1
if ! grep -q "nothing to prune" "$TMP/out2.log"; then
    echo "FAIL: empty-state path did not emit noop" >&2
    cat "$TMP/out2.log" >&2
    exit 1
fi

echo PASS
