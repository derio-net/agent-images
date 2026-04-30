#!/bin/bash
# npm-cache-prune.sh — Weekly cleanup for vk-local's npm file cache.
#
# vk-local retains ~900 MiB of npm tarballs across long-running sessions, which
# inflates the working set seen by cgroup memory accounting. This script:
#   1. Removes cache files untouched for >7d (atime-based — preserves entries
#      reused by active sessions).
#   2. Runs `npm cache verify` so npm rebuilds its index after the deletion and
#      emits a final size report into the log.
#
# The full cache lives under $HOME/.npm/_cacache (npm's default). $HOME is set
# explicitly so npm doesn't fall back to /tmp when invoked from supercronic.
#
# See: frank plan 2026-04-30--agents--vk-local-oom-remediation, Phase 3.

set -u
HOME="${AGENT_HOME:-${HOME:-/home/claude}}"
export HOME

CACHE_DIR="$HOME/.npm/_cacache"

if [ ! -d "$CACHE_DIR" ]; then
    echo "$(date -u +%FT%TZ) cache dir absent at $CACHE_DIR — nothing to prune"
    exit 0
fi

echo "$(date -u +%FT%TZ) starting npm cache prune"
du -sh "$CACHE_DIR" 2>/dev/null | sed 's/^/before: /'

find "$CACHE_DIR" -type f -atime +7 -delete 2>/dev/null

if command -v npm >/dev/null 2>&1; then
    npm cache verify 2>&1 | sed 's/^/verify: /'
else
    echo "npm not on PATH — skipping verify"
fi

du -sh "$CACHE_DIR" 2>/dev/null | sed 's/^/after:  /'
echo "$(date -u +%FT%TZ) done"
