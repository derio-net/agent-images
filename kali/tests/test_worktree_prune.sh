#!/usr/bin/env bash
# test_worktree_prune.sh — harness for scripts/worktree-prune.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export AGENT_HOME="$TMP"
export HOME="$TMP"

# Build a real repo with an orphaned worktree record.
REPO="$AGENT_HOME/repos/sample"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" -c user.email=test@test -c user.name=test commit -q --allow-empty -m bootstrap

WORKTREE="$TMP/dead-worktree"
git -C "$REPO" worktree add -q -b dead-branch "$WORKTREE"
# Confirm record exists.
test -d "$REPO/.git/worktrees/dead-worktree"
# Delete the checkout dir without `git worktree remove` — leaves the record orphaned.
rm -rf "$WORKTREE"

# Backdate the record so --expire=1.day.ago picks it up.
find "$REPO/.git/worktrees/dead-worktree" -type f -exec \
    touch -t "$(date -u -d '2 days ago' +%Y%m%d%H%M)" {} +

# Repo lacking .git directory entirely — script must skip it gracefully.
mkdir -p "$AGENT_HOME/repos/no-git"

bash "$SCRIPT_DIR/scripts/worktree-prune.sh" >"$TMP/out.log" 2>&1

if [[ -d "$REPO/.git/worktrees/dead-worktree" ]]; then
    echo "FAIL: orphaned worktree record was not pruned" >&2
    cat "$TMP/out.log" >&2
    exit 1
fi

# Empty state: no repos dir.
rm -rf "$AGENT_HOME/repos"
bash "$SCRIPT_DIR/scripts/worktree-prune.sh" >"$TMP/out2.log" 2>&1
if ! grep -q "nothing to prune" "$TMP/out2.log"; then
    echo "FAIL: empty-state path did not emit noop" >&2
    cat "$TMP/out2.log" >&2
    exit 1
fi

echo PASS
