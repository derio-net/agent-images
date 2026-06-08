#!/usr/bin/env bash
# test_credential_migrate.sh — harness for base/opt/agent-init.d/02-credential-migrate.
#
# The script lives in base/ and is shared across all agent-images children.
# It runs on every boot from agent-init.d, detects an OLD gitconfig GitHub
# credential helper on the persistent volume, and re-copies the image's
# /opt/gitconfig (which now prefers the mounted App token at
# /var/run/github/token).
#
# Migrates ANY older GitHub-token helper:
#   - Legacy:    contains `password=$GITHUB_TOKEN`
#   - tini-era:  contains `/proc/1/environ`
#   - s6-envdir: reads /run/s6/basedir/env/GITHUB_TOKEN but NOT the new path
# Leaves untouched: a config already on /var/run/github/token, or one with no
# GitHub credential helper at all.
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

    # Stage the CURRENT /opt/gitconfig (file-aware helper) the script copies from.
    local fake_opt="$TMP/$label-opt"
    mkdir -p "$fake_opt"
    cat > "$fake_opt/gitconfig" <<'GIT'
[user]
	email = clawdia-ai-assistant@gmail.com
	name = Clawdia
[credential]
	helper = "!f() { for t in /var/run/github/token /run/s6/basedir/env/GITHUB_TOKEN; do [ -r \"$t\" ] || continue; echo username=x-access-token; printf 'password=%s\\n' \"$(cat \"$t\")\"; return; done; }; f"
GIT

    sed "s|/opt/gitconfig|$fake_opt/gitconfig|g" "$SCRIPT" > "$TMP/$label.sh"
    chmod +x "$TMP/$label.sh"

    AGENT_HOME="$agent_home" HOME="$agent_home" bash "$TMP/$label.sh" >"$TMP/$label.log" 2>&1

    local sha_after sha_target
    sha_after="$(sha256sum "$agent_home/.gitconfig" | cut -d' ' -f1)"
    sha_target="$(sha256sum "$fake_opt/gitconfig" | cut -d' ' -f1)"

    case "$expect_migrated" in
        yes)
            if [ "$sha_after" = "$sha_before" ]; then
                printf 'FAIL [%s]: gitconfig was NOT migrated but should have been\n' "$label" >&2
                cat "$TMP/$label.log" >&2; exit 1
            fi
            if [ "$sha_after" != "$sha_target" ]; then
                printf 'FAIL [%s]: post-migration gitconfig does not match /opt/gitconfig\n' "$label" >&2
                exit 1
            fi
            ;;
        no)
            if [ "$sha_after" != "$sha_before" ]; then
                printf 'FAIL [%s]: gitconfig was migrated but should NOT have been\n' "$label" >&2
                cat "$TMP/$label.log" >&2; exit 1
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

# Case 3: s6-envdir-only helper (no App-token file path) — must now MIGRATE.
run_case s6_envdir '[credential]
	helper = "!f() { echo username=clawdia-ai-assistant; printf '"'"'password=%s\\n'"'"' \"$(< /run/s6/basedir/env/GITHUB_TOKEN)\"; }; f"' yes

# Case 4: dash-broken App-token reader ($(< …), has the new path but empty under
# dash) — must MIGRATE to the $(cat …) form.
run_case dash_broken '[credential]
	helper = "!f() { for t in /var/run/github/token /run/s6/basedir/env/GITHUB_TOKEN; do [ -r \"$t\" ] || continue; echo username=x-access-token; printf '"'"'password=%s\\n'"'"' \"$(< \"$t\")\"; return; done; }; f"' yes

# Case 5: already on the dash-safe App-token reader ($(cat …)) — must NOT migrate.
run_case current_filereader '[credential]
	helper = "!f() { for t in /var/run/github/token /run/s6/basedir/env/GITHUB_TOKEN; do [ -r \"$t\" ] || continue; echo username=x-access-token; printf '"'"'password=%s\\n'"'"' \"$(cat \"$t\")\"; return; done; }; f"' no

# Case 6: unrelated user gitconfig (no GitHub credential helper) — must NOT migrate.
run_case unrelated '[user]
	name = Some Other Identity' no

echo "PASS: 02-credential-migrate upgrades all older GitHub helpers (legacy/proc/s6) and skips current/unrelated configs."
