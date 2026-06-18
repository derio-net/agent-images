#!/usr/bin/env bash
# install-native-harness.sh — install/refresh the NATIVE build of an agent harness
# into the PV-resident $HOME/.local (self-updating, PATH-preferred over the npm
# bootstrap shim). MEMORY-SAFE: plain curl of the published binary, NOT the
# harness's own `install` subcommand, which buffers the whole download in-process
# (~245MB ×17 ≈ 4GiB peak for claude) and group-OOMs a memory-limited pod.
#
# Idempotent (skips when the latest is already installed) and FAIL-OPEN (any
# network/checksum failure leaves the existing build / npm bootstrap in place and
# returns 0 — never blocks container boot). Runs as the agent user (cont-init,
# non-root s6), so it writes $HOME/.local directly.
#
# Usage: install-native-harness.sh <harness> [<harness> …]   (default: claude)
set -uo pipefail

CURL_MAX_META="${NATIVE_HARNESS_CURL_META_TIMEOUT:-20}"
CURL_MAX_DL="${NATIVE_HARNESS_CURL_DL_TIMEOUT:-300}"

# --- claude: native build from the Anthropic releases CDN -----------------------
install_claude() {
    local DL="${CLAUDE_NATIVE_DL:-https://downloads.claude.ai/claude-code-releases}"
    local version installed checksum vdir tmp
    version=$(curl -fsSL --max-time "$CURL_MAX_META" "$DL/latest" 2>/dev/null) || {
        echo "= native-claude: cannot reach $DL/latest — leaving the npm bootstrap in place"; return 0; }
    [ -n "$version" ] || { echo "= native-claude: empty latest version — skip"; return 0; }
    vdir="$HOME/.local/share/claude/versions"
    installed=$(basename "$(readlink "$HOME/.local/bin/claude" 2>/dev/null || true)" 2>/dev/null || true)
    if [ "$installed" = "$version" ] && [ -x "$vdir/$version" ]; then
        echo "✓ native-claude: $version already installed (skip download)"; return 0
    fi
    echo "→ native-claude: installing $version (memory-safe curl)…"
    checksum=$(curl -fsSL --max-time "$CURL_MAX_META" "$DL/$version/manifest.json" 2>/dev/null \
                | jq -r '.platforms["linux-x64"].checksum' 2>/dev/null) || true
    [ -n "${checksum:-}" ] && [ "$checksum" != "null" ] || {
        echo "= native-claude: manifest/checksum unavailable — skip (bootstrap stands)"; return 0; }
    mkdir -p "$vdir" "$HOME/.local/bin"
    tmp="$vdir/$version.tmp.$$"
    if ! curl -fsSL --max-time "$CURL_MAX_DL" -o "$tmp" "$DL/$version/linux-x64/claude"; then
        echo "= native-claude: download failed — keeping previous build"; rm -f "$tmp"; return 0
    fi
    if ! echo "$checksum  $tmp" | sha256sum -c --status; then
        echo "✘ native-claude: checksum mismatch — discarding download"; rm -f "$tmp"; return 0
    fi
    chmod +x "$tmp" && mv -f "$tmp" "$vdir/$version"
    ln -sfn "$vdir/$version" "$HOME/.local/bin/claude"
    echo "✓ native-claude: $version → $HOME/.local/bin/claude"
}

# Add further native harnesses here (e.g. install_opencode) as they gain a
# published binary worth pinning on the PV. codex/opencode are npm (managed by the
# inventory reconciler); agy is a build-time binary — neither needs this path.
install_one() {
    case "$1" in
        claude) install_claude ;;
        *) echo "= native-harness: no native installer defined for '$1' (npm/binary bootstrap stands)";;
    esac
}

main() {
    local had_any=0
    for h in "${@:-claude}"; do had_any=1; install_one "$h"; done
    [ "$had_any" = 1 ] || install_one claude
    return 0   # fail-open overall: never fail container boot
}

main "$@"
