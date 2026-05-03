#!/usr/bin/env bash
# install-inventory.sh — Layer-2 inventory installer.
#   * Idempotent: re-running with no changes is a quick no-op.
#   * Fail-open: a single broken install logs and continues; never blocks sshd.
#   * Source of truth: /etc/ruflo-shell/inventory.yaml (mounted ConfigMap).
#   * On any failure, fires a Telegram alert via notify-telegram.sh.
#
# NOT `set -e` — failures are accumulated, not propagated.
set -uo pipefail

# shellcheck source=/dev/null
. /usr/local/lib/ruflo-shell/lib.sh
ruflo_shell_init_dirs

INVENTORY="${INVENTORY:-/etc/ruflo-shell/inventory.yaml}"
LOG="${RUFLO_SHELL_LOG_DIR}/40-shell-inventory.log"
NOTIFY=/usr/local/lib/ruflo-shell/notify-telegram.sh

exec > >(tee -a "$LOG") 2>&1

echo "=== ruflo-shell-reconcile @ $(date -Iseconds) ==="

# Make mise shims and the rustup-managed cargo bin visible for the npm-global
# and cargo sections below. Prepended unconditionally; missing dirs are a
# no-op until the relevant runtime is installed.
export PATH="${HOME}/.local/share/mise/shims:${HOME}/.cargo/bin:${PATH}"

if [[ ! -f "$INVENTORY" ]]; then
    echo "WARN: $INVENTORY missing; nothing to do"
    ruflo_shell_motd_write "⚠ ruflo-shell: inventory file missing"
    exit 0
fi

declare -i installed=0 already=0 removed=0 failed=0
declare -a failures=()

run() {
    local label="$1"
    shift
    if "$@"; then
        echo "✓ $label"
        return 0
    else
        local rc=$?
        echo "✗ $label (rc=$rc)"
        failures+=("$label")
        failed+=1
        return 1
    fi
}

# Read a top-level list from inventory.yaml. Returns one item per line.
yaml_list() {
    python3 -c "
import sys, yaml
d = yaml.safe_load(open('$INVENTORY')) or {}
for x in (d.get('$1') or []):
    print(x)
"
}

# Read a list under 'removed.<key>'. Returns one item per line.
yaml_removed_list() {
    python3 -c "
import sys, yaml
d = yaml.safe_load(open('$INVENTORY')) or {}
for x in ((d.get('removed') or {}).get('$1') or []):
    print(x)
"
}

assert_manager() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "✗ manager '$cmd' missing from image; cannot reconcile its section"
        failures+=("manager-missing:$cmd")
        failed+=1
        return 1
    fi
}

# --- mise ---
if assert_manager mise; then
    while IFS= read -r tool; do
        [[ -z "$tool" ]] && continue
        if mise where "$tool" >/dev/null 2>&1; then
            already+=1
            echo "= mise $tool"
            continue
        fi
        run "mise install $tool" mise install "$tool" && installed+=1
    done < <(yaml_list mise)

    while IFS= read -r tool; do
        [[ -z "$tool" ]] && continue
        run "mise uninstall $tool" mise uninstall "$tool" && removed+=1
    done < <(yaml_removed_list mise)
fi

# --- npm-global --- (npm comes from a runtime managed by mise; skip section if missing)
if command -v npm >/dev/null 2>&1; then
    while IFS= read -r pkg; do
        [[ -z "$pkg" ]] && continue
        if npm ls -g "$pkg" --depth=0 >/dev/null 2>&1; then
            already+=1
            echo "= npm $pkg"
            continue
        fi
        run "npm i -g $pkg" npm install -g "$pkg" && installed+=1
    done < <(yaml_list npm-global)

    while IFS= read -r pkg; do
        [[ -z "$pkg" ]] && continue
        run "npm rm -g $pkg" npm uninstall -g "$pkg" && removed+=1
    done < <(yaml_removed_list npm-global)
else
    if [[ -n "$(yaml_list npm-global)" || -n "$(yaml_removed_list npm-global)" ]]; then
        echo "= npm-global section declared but no npm on PATH (install node via mise first); skipping"
    fi
fi

# --- pipx ---
if assert_manager pipx; then
    while IFS= read -r pkg; do
        [[ -z "$pkg" ]] && continue
        if pipx list --short 2>/dev/null | awk '{print $1}' | grep -qx "$pkg"; then
            already+=1
            echo "= pipx $pkg"
            continue
        fi
        run "pipx install $pkg" pipx install "$pkg" && installed+=1
    done < <(yaml_list pipx)

    while IFS= read -r pkg; do
        [[ -z "$pkg" ]] && continue
        run "pipx uninstall $pkg" pipx uninstall "$pkg" && removed+=1
    done < <(yaml_removed_list pipx)
fi

# --- cargo --- (cargo comes from rustup-installed toolchain on PV; skip if missing)
if command -v cargo >/dev/null 2>&1; then
    while IFS= read -r crate; do
        [[ -z "$crate" ]] && continue
        if cargo install --list 2>/dev/null | awk '/^[a-zA-Z0-9_-]+ /{print $1}' | grep -qx "$crate"; then
            already+=1
            echo "= cargo $crate"
            continue
        fi
        run "cargo install $crate" cargo install "$crate" && installed+=1
    done < <(yaml_list cargo)

    while IFS= read -r crate; do
        [[ -z "$crate" ]] && continue
        run "cargo uninstall $crate" cargo uninstall "$crate" && removed+=1
    done < <(yaml_removed_list cargo)
else
    if [[ -n "$(yaml_list cargo)" || -n "$(yaml_removed_list cargo)" ]]; then
        echo "= cargo section declared but no cargo on PATH (run \`rustup toolchain install stable\` or \`mise install rust@stable\` first); skipping"
    fi
fi

echo "=== summary: installed=$installed already=$already removed=$removed failed=$failed ==="

if (( failed > 0 )); then
    ruflo_shell_motd_write "$(printf '⚠ ruflo-shell: %d install(s) failed on last reconcile (%s)\n  See: %s' \
        "$failed" "$(IFS=,; echo "${failures[*]}")" "$LOG")"
    "$NOTIFY" \
        "ruflo-shell: $failed install(s) failed on boot" \
        "$(printf '%s\n' "${failures[@]}")" || true
else
    ruflo_shell_motd_write "$(printf '✓ ruflo-shell: %d installed, %d already present, %d removed @ %s' \
        "$installed" "$already" "$removed" "$(date -Iseconds)")"
fi

exit 0  # always succeed — fail-open
