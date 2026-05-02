#!/bin/bash
# worktree-prune.sh — Daily cleanup for vibe-kanban worktree records.
#
# vibe-kanban creates one git worktree per execution under /var/tmp (tmpfs that
# is wiped on pod restart). Each canonical repo at $HOME/repos/<name>/ keeps
# administrative records for those worktrees in .git/worktrees/, and orphaned
# records hold ~17 MiB of in-process heap residue per repo per stale worktree
# (per the 2026-04-22 memprofile). `git worktree prune` removes records whose
# checkout directory no longer exists.
#
# We iterate every git directory directly under $HOME/repos/. This is the
# canonical project root for vibe-kanban on Frank — worktrees themselves live
# under /var/tmp/vibe-kanban/worktrees/ and link back via the .git gitdir file.
#
# A flock guard prevents overlap with a manual `kubectl exec` invocation.
#
# HOME is set explicitly (defensive — supercronic does export HOME under s6,
# but the AGENT_HOME → HOME chain matches the convention used by other scripts
# in /opt/scripts/).
#
# See: frank plan 2026-04-30--agents--vk-local-oom-remediation, Phase 3.

set -uo pipefail
HOME="${AGENT_HOME:-${HOME:-/home/claude}}"
REPO_ROOT="$HOME/repos"
LOCK_DIR="$HOME/.willikins-agent"
LOCK_FILE="$LOCK_DIR/worktree-prune.lock"

mkdir -p "$LOCK_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date -u +%FT%TZ) another worktree-prune is running — exiting"
    exit 0
fi

if [ ! -d "$REPO_ROOT" ]; then
    echo "$(date -u +%FT%TZ) repo root absent at $REPO_ROOT — nothing to prune"
    exit 0
fi

echo "$(date -u +%FT%TZ) starting worktree prune"

shopt -s nullglob
exit_rc=0
for gitdir in "$REPO_ROOT"/*/.git; do
    repo="$(dirname "$gitdir")"
    # Skip submodule-style .git files that are not real git directories.
    [ -d "$gitdir" ] || continue
    echo "--- $repo"
    if ! git --git-dir="$gitdir" worktree prune --verbose --expire=1.day.ago 2>&1; then
        echo "WARN: prune failed for $repo"
        exit_rc=1
    fi
done

echo "$(date -u +%FT%TZ) done"
exit "$exit_rc"
