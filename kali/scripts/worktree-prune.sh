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
# See: frank plan 2026-04-30--agents--vk-local-oom-remediation, Phase 3.

set -u
HOME="${AGENT_HOME:-${HOME:-/home/claude}}"
REPO_ROOT="$HOME/repos"

if [ ! -d "$REPO_ROOT" ]; then
    echo "$(date -u +%FT%TZ) repo root absent at $REPO_ROOT — nothing to prune"
    exit 0
fi

echo "$(date -u +%FT%TZ) starting worktree prune"

shopt -s nullglob
for gitdir in "$REPO_ROOT"/*/.git; do
    repo="$(dirname "$gitdir")"
    # Skip submodule-style .git files that are not real git directories.
    [ -d "$gitdir" ] || continue
    echo "--- $repo"
    git --git-dir="$gitdir" worktree prune --verbose --expire=1.day.ago 2>&1 || true
done

echo "$(date -u +%FT%TZ) done"
