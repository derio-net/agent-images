#!/usr/bin/env bash
# install-inventory.sh — Layer-2 inventory installer.
#   * Idempotent: re-running with no changes is a quick no-op.
#   * Fail-open: a single broken install logs and continues; never blocks sshd.
#   * Source of truth: /etc/hermes-agent-shell/inventory.yaml (mounted ConfigMap).
#   * On any failure, fires a Telegram alert via notify-telegram.sh.
#
# YAML parsing deliberately uses /usr/bin/python3 + apt-installed PyYAML
# (python3-yaml). At cont-init.d boot time mise shims are not yet on PATH for
# the script's own environment, and we want YAML parsing to keep working
# even before any mise-managed runtimes land on the PV.
#
# NOT `set -e` — failures are accumulated, not propagated.
set -uo pipefail

# Source path resolves to the script's own directory so the same code runs
# both in the baked image (under /usr/local/lib/hermes-agent-shell) and from
# a checked-out tree during bats tests. `readlink -f` resolves the symlink
# at /usr/local/bin/hermes-agent-shell-reconcile → this file; without it,
# BASH_SOURCE[0] is the symlink path and `_self_dir` lands in /usr/local/bin/
# where lib.sh doesn't exist — the source silently fails (no `set -e`),
# functions go undefined, and `set -u` trips on the first sibling-var read.
_self_dir="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=/dev/null
. "$_self_dir/lib.sh"
hermes_agent_shell_init_dirs

INVENTORY="${INVENTORY:-/etc/hermes-agent-shell/inventory.yaml}"
LOG="${HERMES_AGENT_SHELL_LOG_DIR}/40-shell-inventory.log"
NOTIFY="$_self_dir/notify-telegram.sh"

exec > >(tee -a "$LOG") 2>&1

echo "=== hermes-agent-shell-reconcile @ $(date -Iseconds) ==="

# Make mise shims and the rustup-managed cargo bin visible for the npm-global
# and cargo sections below. Prepended unconditionally; missing dirs are a
# no-op until the relevant runtime is installed.
export PATH="${HOME}/.local/share/mise/shims:${HOME}/.cargo/bin:${PATH}"

if [[ ! -f "$INVENTORY" ]]; then
    echo "WARN: $INVENTORY missing; nothing to do"
    hermes_agent_shell_motd_write "⚠ hermes-agent-shell: inventory file missing"
    exit 0
fi

declare -i installed=0 already=0 removed=0 failed=0
declare -a failures=()

run() {
    local label="$1"
    shift
    local rc
    if "$@"; then
        echo "✓ $label"
        return 0
    fi
    # Capture rc immediately on the first line of the failure path so any
    # future refactor that adds a command above this line does not silently
    # corrupt rc (e.g. an `echo`'s `$?` shadowing the real failure).
    rc=$?
    echo "✗ $label (rc=$rc)"
    failures+=("$label")
    failed+=1
    return "$rc"
}

# Read a top-level list from inventory.yaml. Returns one item per line.
yaml_list() {
    /usr/bin/python3 -c "
import sys, yaml
d = yaml.safe_load(open('$INVENTORY')) or {}
for x in (d.get('$1') or []):
    print(x)
"
}

# Read a list under 'removed.<key>'. Returns one item per line.
yaml_removed_list() {
    /usr/bin/python3 -c "
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
        else
            run "mise install $tool" mise install "$tool" && installed+=1
        fi
        # Activate globally so the shim dispatches to this runtime; without it
        # npm/cargo fall through to the root-owned system prefix → EACCES.
        # Unconditional + idempotent: also heals PVs left unactivated by older
        # versions of this script. (#56)
        run "mise use -g $tool" mise use -g "$tool"
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
        # `cargo install --list` output:
        #     ripgrep v14.1.0:
        #         rg
        #     cargo-binstall v1.6.0:
        #         cargo-binstall
        # Package lines start at column 0; binary-name lines are indented.
        # Strip the version+colon to get just the package name.
        if cargo install --list 2>/dev/null \
            | awk '/^[^[:space:]]/{sub(/ .*$/, ""); print}' \
            | grep -qx "$crate"; then
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

# === multi-harness standard extension =======================================
# Three new keys per docs/standards/multi-harness-shells.md:
#   harnesses:    pinned/floating CLI versions, refreshed via `<h> update`
#   mcp-servers:  per-harness mcp.json merge (idempotent by name)
#   skills:       per-harness git-cloned skills/plugins under $HOME
#
# YAML parsing for these sections uses yq (binary-distributed, no Python
# import) so the same code paths run cleanly in bats tests that may not have
# PyYAML available. The existing keys above keep their python+PyYAML path
# to minimise diff against paperclip-shell's baseline.

if command -v yq >/dev/null 2>&1; then

    # --- harnesses ---
    if yq -e 'has("harnesses")' "$INVENTORY" >/dev/null 2>&1; then
        # Stream "name<TAB>pin" pairs so values with spaces/quotes stay intact.
        while IFS=$'\t' read -r harness pin; do
            [[ -z "$harness" ]] && continue
            if ! command -v "$harness" >/dev/null 2>&1; then
                echo "= warn: harness $harness pinned to '$pin' but CLI not on PATH; skipping update"
                continue
            fi
            run "harness $harness update (pin=$pin)" "$harness" update && installed+=1
        done < <(yq -r '.harnesses | to_entries[] | "\(.key)\t\(.value)"' "$INVENTORY")
    fi

    # --- mcp-servers ---
    # Merge each entry into $HOME/.<harness>/mcp.json by .name (idempotent).
    if yq -e 'has("mcp-servers")' "$INVENTORY" >/dev/null 2>&1; then
        while IFS= read -r harness; do
            [[ -z "$harness" ]] && continue
            mcp_path="$HOME/.${harness}/mcp.json"
            mkdir -p "$(dirname "$mcp_path")"
            [[ -f "$mcp_path" ]] || echo '{"mcpServers":{}}' > "$mcp_path"
            entries=$(mktemp)
            yq -o=json ".\"mcp-servers\".\"$harness\"" "$INVENTORY" > "$entries"
            tmp=$(mktemp)
            if jq --slurpfile new "$entries" '
                  .mcpServers = (
                      (.mcpServers // {}) as $existing
                      | reduce $new[0][] as $e ($existing;
                          .[$e.name] = ($e | del(.name)))
                  )' "$mcp_path" > "$tmp" 2>/dev/null; then
                mv "$tmp" "$mcp_path"
                count=$(jq '.mcpServers | length' "$mcp_path")
                echo "= mcp-servers/$harness reconciled ($count total)"
                installed+=1
            else
                echo "✗ mcp-servers/$harness: jq merge failed"
                failures+=("mcp-servers/$harness")
                failed+=1
                rm -f "$tmp"
            fi
            rm -f "$entries"
        done < <(yq -r '."mcp-servers" | keys | .[]' "$INVENTORY")
    fi

    # --- skills ---
    # Clone (or fast-forward to ref) into $HOME/.<harness>/skills/<name>.
    # Entries are streamed as "harness<TAB>name<TAB>source<TAB>ref" so the
    # whole section runs in ONE while-loop with no pipe — counter mutations
    # (installed/already/failed) persist in the current shell rather than
    # being lost to a subshell. yq emits "null" for a missing .ref; bash
    # normalises that to HEAD below (avoids a nested-quote yq interpolation).
    if yq -e 'has("skills")' "$INVENTORY" >/dev/null 2>&1; then
        while IFS=$'\t' read -r harness name source ref; do
            [[ -z "$harness" || -z "$name" ]] && continue
            skills_dir="$HOME/.${harness}/skills"
            mkdir -p "$skills_dir"
            target="$skills_dir/$name"
            url="${source#git+}"
            [[ "$ref" == "null" || -z "$ref" ]] && ref=HEAD
            if [[ -d "$target/.git" ]]; then
                if (cd "$target" && git fetch -q origin 2>/dev/null && git checkout -q "$ref" 2>/dev/null); then
                    already+=1
                    echo "= skill $harness/$name checked out at $ref"
                else
                    echo "✗ skill $harness/$name update to $ref failed"
                    failures+=("skills/$harness/$name")
                    failed+=1
                fi
            else
                if git clone -q "$url" "$target" 2>/dev/null; then
                    (cd "$target" && git checkout -q "$ref" 2>/dev/null) || true
                    installed+=1
                    echo "✓ skill $harness/$name cloned from $url"
                else
                    echo "✗ skill $harness/$name clone from $url failed"
                    failures+=("skills/$harness/$name")
                    failed+=1
                fi
            fi
        done < <(yq -r '.skills | to_entries[] | .key as $h | .value[] | [$h, .name, .source, (.ref // "HEAD")] | @tsv' "$INVENTORY")
    fi

    # --- removed.* for the three new keys ---
    # Guarded independently of the additive blocks above: a removal-only
    # inventory carries `removed:` without the matching top-level key.
    if yq -e 'has("removed")' "$INVENTORY" >/dev/null 2>&1; then

        # removed.harnesses — declarative uninstall. Most harness CLIs do not
        # expose an `uninstall` subcommand, so we delete a PV-installed shim at
        # $HOME/.local/bin/<h> if present, then warn-only otherwise.
        while IFS= read -r harness; do
            [[ -z "$harness" ]] && continue
            if [[ -e "$HOME/.local/bin/$harness" ]]; then
                rm -f "$HOME/.local/bin/$harness" && removed+=1
                echo "✓ removed $HOME/.local/bin/$harness"
            else
                echo "= warn: removed.harnesses.$harness has no PV-installed binary at \$HOME/.local/bin; nothing to remove"
            fi
        done < <(yq -r '.removed.harnesses // [] | .[]' "$INVENTORY")

        # removed.mcp-servers.<harness> — delete named servers from mcp.json.
        while IFS=$'\t' read -r harness name; do
            [[ -z "$harness" || -z "$name" ]] && continue
            mcp_path="$HOME/.${harness}/mcp.json"
            [[ -f "$mcp_path" ]] || continue
            tmp=$(mktemp)
            if jq --arg n "$name" 'del(.mcpServers[$n])' "$mcp_path" > "$tmp" 2>/dev/null; then
                mv "$tmp" "$mcp_path" && removed+=1
                echo "✓ removed mcp-servers/$harness/$name"
            else
                echo "✗ removed.mcp-servers/$harness/$name: jq delete failed"
                failures+=("removed.mcp-servers/$harness/$name")
                failed+=1
                rm -f "$tmp"
            fi
        done < <(yq -r '(.removed."mcp-servers" // {}) | to_entries[] | .key as $h | .value[] | [$h, .] | @tsv' "$INVENTORY")

        # removed.skills.<harness> — delete the cloned skill dir.
        while IFS=$'\t' read -r harness name; do
            [[ -z "$harness" || -z "$name" ]] && continue
            target="$HOME/.${harness}/skills/$name"
            if [[ -d "$target" ]]; then
                rm -rf "$target" && removed+=1
                echo "✓ removed skills/$harness/$name"
            else
                echo "= warn: removed.skills.$harness.$name not present; nothing to remove"
            fi
        done < <(yq -r '(.removed.skills // {}) | to_entries[] | .key as $h | .value[] | [$h, .] | @tsv' "$INVENTORY")
    fi

else
    # yq missing — log once and proceed; the three new sections are skipped.
    if /usr/bin/python3 -c "
import sys, yaml
d = yaml.safe_load(open('$INVENTORY')) or {}
sys.exit(0 if any(k in d for k in ('harnesses','mcp-servers','skills')) else 1)
" 2>/dev/null; then
        echo "= warn: yq not on PATH; harnesses/mcp-servers/skills sections skipped"
    fi
fi
# === end multi-harness standard extension ===================================

echo "=== summary: installed=$installed already=$already removed=$removed failed=$failed ==="

if (( failed > 0 )); then
    hermes_agent_shell_motd_write "$(printf '⚠ hermes-agent-shell: %d install(s) failed on last reconcile (%s)\n  See: %s' \
        "$failed" "$(IFS=,; echo "${failures[*]}")" "$LOG")"
    "$NOTIFY" \
        "hermes-agent-shell: $failed install(s) failed on boot" \
        "$(printf '%s\n' "${failures[@]}")" || true
else
    hermes_agent_shell_motd_write "$(printf '✓ hermes-agent-shell: %d installed, %d already present, %d removed @ %s' \
        "$installed" "$already" "$removed" "$(date -Iseconds)")"
fi

exit 0  # always succeed — fail-open
