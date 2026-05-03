#!/usr/bin/env bash
# test_credential_migrate.sh — harness for base/opt/agent-init.d/02-credential-migrate.
#
# The script lives in base/ and is shared across all agent-images children.
# It runs on every boot from agent-init.d, detects stale gitconfig credential
# helpers on the persistent volume, and re-copies the image's /opt/gitconfig.
#
# Two prior helper shapes need migrating:
#   - Legacy:   contains `password=$GITHUB_TOKEN`
#   - tini-era: contains `/proc/1/environ`
# Current helper reads /run/s6/basedir/env/GITHUB_TOKEN.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO_ROOT/base/opt/agent-init.d/02-credential-migrate"
[ -x "$SCRIPT" ] || chmod +x "$SCRIPT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

run_case() {
    local label="$1" existing_gitconfig="$2" expect_migrated="$3"
    local agent_home="$TMP/$label"
    mkdir -p "$agent_home"
    printf '%s\n' "$existing_gitconfig" > "$agent_home/.gitconfig"
    local sha_before
    sha_before="$(sha256sum "$agent_home/.gitconfig" | cut -d' ' -f1)"

    # Stage a "current" /opt/gitconfig the script can copy from.
    local fake_opt="$TMP/$label-opt"
    mkdir -p "$fake_opt"
    cat > "$fake_opt/gitconfig" <<'GIT'
[user]
	email = clawdia-ai-assistant@gmail.com
	name = Clawdia
[credential]
	helper = "!f() { echo username=clawdia-ai-assistant; printf 'password=%s\\n' \"$(< /run/s6/basedir/env/GITHUB_TOKEN)\"; }; f"
GIT

    # Sandbox /opt by running with a script-local PATH prefix that swaps the
    # path. Easiest cross-platform approach: copy the script and rewrite the
    # /opt/gitconfig path before exec.
    sed "s|/opt/gitconfig|$fake_opt/gitconfig|g" "$SCRIPT" > "$TMP/$label.sh"
    chmod +x "$TMP/$label.sh"

    AGENT_HOME="$agent_home" HOME="$agent_home" bash "$TMP/$label.sh" >"$TMP/$label.log" 2>&1

    local sha_after
    sha_after="$(sha256sum "$agent_home/.gitconfig" | cut -d' ' -f1)"
    local sha_target
    sha_target="$(sha256sum "$fake_opt/gitconfig" | cut -d' ' -f1)"

    case "$expect_migrated" in
        yes)
            if [ "$sha_after" = "$sha_before" ]; then
                printf 'FAIL [%s]: gitconfig was NOT migrated but should have been\n' "$label" >&2
                cat "$TMP/$label.log" >&2
                exit 1
            fi
            if [ "$sha_after" != "$sha_target" ]; then
                printf 'FAIL [%s]: post-migration gitconfig does not match /opt/gitconfig\n' "$label" >&2
                exit 1
            fi
            ;;
        no)
            if [ "$sha_after" != "$sha_before" ]; then
                printf 'FAIL [%s]: gitconfig was migrated but should NOT have been\n' "$label" >&2
                cat "$TMP/$label.log" >&2
                exit 1
            fi
            ;;
    esac
    printf 'OK   [%s] expect_migrated=%s\n' "$label" "$expect_migrated"
}

# Case 1: legacy env-var helper — must migrate.
run_case legacy_envvar '[credential]
	helper = "!f() { echo username=clawdia-ai-assistant; echo password=$GITHUB_TOKEN; }; f"' yes

# Case 2: /proc/1/environ helper — must migrate.
run_case proc_environ '[credential]
	helper = "!f() { echo username=clawdia-ai-assistant; echo \"password=$(tr \"\\0\" \"\\n\" < /proc/1/environ | sed -n \"s/^GITHUB_TOKEN=//p\")\"; }; f"' yes

# Case 3: already on the s6 envdir — must NOT migrate.
run_case s6_envdir '[credential]
	helper = "!f() { echo username=clawdia-ai-assistant; printf '"'"'password=%s\\n'"'"' \"$(< /run/s6/basedir/env/GITHUB_TOKEN)\"; }; f"' no

# Case 4: unrelated user gitconfig (no GitHub credential helper) — must NOT migrate.
run_case unrelated '[user]
	name = Some Other Identity' no

echo "PASS: 02-credential-migrate detects both legacy + /proc/1/environ helpers and skips current/unrelated configs."
