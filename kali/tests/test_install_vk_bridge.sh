#!/usr/bin/env bash
# test_install_vk_bridge.sh — harness for etc/cont-init.d/55-install-vk-bridge.
# Covers four cases:
#   1. First boot (no PVC install): runs `uv tool install` AND writes wrapper.
#   2. Idempotent re-run (PVC install matches pin): skips uv tool install,
#      still rewrites the wrapper (cheap; self-heals drift).
#   3. Version drift (PVC install at older pin): re-runs `uv tool install`.
#   4. Pin override via env: VK_BRIDGE_PIN can be overridden by the caller.
#
# Stubs `uv` by prepending a fake binary to PATH that records invocations
# to UV_LOG and serves a fake `uv tool dir` pointing at a temp directory.
# Real network installs would make the test brittle.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SCRIPT_DIR/etc/cont-init.d/55-install-vk-bridge"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Wrap the s6 shebang for portable invocation.
SCRIPT_COPY="$TMP/55-install-vk-bridge"
{ echo '#!/usr/bin/env bash'; tail -n +2 "$SCRIPT"; } > "$SCRIPT_COPY"
chmod +x "$SCRIPT_COPY"

# Fake `uv` binary. Records every invocation to UV_LOG, serves canned
# output for `uv tool dir`, and, when invoked as `uv tool install`,
# materializes a fake vk tool dir with a `bin/python` that reports the
# requested version (parsed out of the --from arg).
#
# Stored as a template — install_fake_uv() copies it into each case's
# $HOME/.local/bin/uv, which is on the script's own PATH (the script
# overwrites PATH to a deterministic value for cron consistency).
FAKE_UV_TEMPLATE="$TMP/fake-uv"
cat > "$FAKE_UV_TEMPLATE" <<'EOF'
#!/usr/bin/env bash
set -e
echo "uv $*" >> "$UV_LOG"
if [ "${1:-}" = "tool" ] && [ "${2:-}" = "dir" ]; then
    echo "$UV_TOOL_DIR"
    exit 0
fi
if [ "${1:-}" = "tool" ] && [ "${2:-}" = "install" ]; then
    # Parse the version out of `--from "vk @ git+...@v2.2.11"`.
    from_arg=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --from) shift; from_arg="$1"; shift;;
            *) shift;;
        esac
    done
    ver="${from_arg##*@v}"
    ver="${ver%%[^0-9.]*}"   # strip anything not version-shaped
    [ -n "$ver" ] || ver="0.0.0"
    mkdir -p "$UV_TOOL_DIR/vk/bin"
    cat > "$UV_TOOL_DIR/vk/bin/python" <<PYEOF
#!/usr/bin/env bash
# Fake python that only knows how to report vk's installed version.
if [ "\$1" = "-c" ]; then
    case "\$2" in
        *"importlib.metadata"*) echo "$ver"; exit 0;;
    esac
fi
echo "fake python: unsupported invocation: \$*" >&2
exit 1
PYEOF
    chmod +x "$UV_TOOL_DIR/vk/bin/python"
    exit 0
fi
echo "fake uv: unsupported invocation: $*" >&2
exit 1
EOF
chmod +x "$FAKE_UV_TEMPLATE"

install_fake_uv() {
    local home="$1"
    mkdir -p "$home/.local/bin"
    cp "$FAKE_UV_TEMPLATE" "$home/.local/bin/uv"
    touch "$home/uv.log"
}

run_init() {
    local home="$1"
    local pin="${2:-v2.2.11}"
    UV_LOG="$home/uv.log" \
    UV_TOOL_DIR="$home/.local/share/uv/tools" \
    HOME="$home" AGENT_HOME="$home" VK_BRIDGE_PIN="$pin" \
        bash "$SCRIPT_COPY"
}

assert_grep() {
    grep -q "$1" "$2" || { echo "FAIL: expected '$1' in $2"; cat "$2"; exit 1; }
}

count_lines() {
    # grep -c always prints a count, but exits 1 on zero matches — the
    # || true keeps `set -e` from killing the harness when nothing matches.
    grep -c "$1" "$2" 2>/dev/null || true
}

# ---- Case 1: first boot — installs vk and writes wrapper ----
H1="$TMP/case1"
mkdir -p "$H1"
install_fake_uv "$H1"
run_init "$H1" v2.2.11
test -x "$H1/.local/bin/vk-bridge" || { echo "case1: wrapper missing"; exit 1; }
assert_grep '^uv tool install' "$H1/uv.log"
assert_grep 'vk.bridge' "$H1/.local/bin/vk-bridge"
grep -q "$H1/.local/share/uv/tools/vk/bin/python" "$H1/.local/bin/vk-bridge" \
    || { echo "case1: wrapper does not point at uv tool python"; cat "$H1/.local/bin/vk-bridge"; exit 1; }
echo "case1: first-boot install OK"

# ---- Case 2: idempotent re-run — already at target pin, no reinstall ----
> "$H1/uv.log"
run_init "$H1" v2.2.11
installs="$(count_lines 'tool install' "$H1/uv.log")"
[ "$installs" = "0" ] || { echo "case2: expected 0 'tool install' calls on re-run, got $installs"; cat "$H1/uv.log"; exit 1; }
test -x "$H1/.local/bin/vk-bridge" || { echo "case2: wrapper missing after re-run"; exit 1; }
echo "case2: idempotent re-run OK (no reinstall)"

# ---- Case 3: version drift — pin moved forward, init re-installs ----
> "$H1/uv.log"
run_init "$H1" v2.3.0
assert_grep '^uv tool install' "$H1/uv.log"
assert_grep 'v2.3.0' "$H1/uv.log"
echo "case3: version-drift reinstall OK"

# ---- Case 4: pin override via env — caller-supplied VK_BRIDGE_PIN wins ----
H4="$TMP/case4"
mkdir -p "$H4"
install_fake_uv "$H4"
run_init "$H4" v1.2.3
assert_grep 'v1.2.3' "$H4/uv.log"
echo "case4: env-pin override OK"

echo "all tests passed"
