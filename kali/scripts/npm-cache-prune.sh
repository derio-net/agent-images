#!/bin/bash
# npm-cache-prune.sh — Weekly cleanup for vk-local's npm file cache.
#
# vk-local retains ~900 MiB of npm tarballs across long-running sessions, which
# inflates the working set seen by cgroup memory accounting. This script:
#   1. Detects whether atime updates are reliable on the cache mount (PVCs may
#      mount with `noatime`, in which case `-atime +7` would never match).
#      When atime is unreliable, falls back to mtime (file creation time, which
#      for npm cache content is when it was downloaded — slightly more
#      conservative but correct).
#   2. Removes cache files untouched for >7d.
#   3. Runs `npm cache verify` so npm rebuilds its index after the deletion and
#      emits a final size report into the log.
#
# A flock guard prevents overlap with a manual `kubectl exec` invocation or a
# delayed previous tick.
#
# HOME is set explicitly (defensive — supercronic does export HOME under s6,
# but `set -u` would trip if it ever did not, and the AGENT_HOME → HOME chain
# matches the convention used by other scripts in /opt/scripts/).
#
# See: frank plan 2026-04-30--agents--vk-local-oom-remediation, Phase 3.

set -uo pipefail
HOME="${AGENT_HOME:-${HOME:-/home/claude}}"
export HOME

CACHE_DIR="$HOME/.npm/_cacache"
LOCK_DIR="$HOME/.willikins-agent"
LOCK_FILE="$LOCK_DIR/npm-cache-prune.lock"

mkdir -p "$LOCK_DIR"

# flock single-instance guard. -n: fail immediately if another run holds the
# lock. The fd stays open for the script's lifetime; lock releases on exit.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date -u +%FT%TZ) another npm-cache-prune is running — exiting"
    exit 0
fi

if [ ! -d "$CACHE_DIR" ]; then
    echo "$(date -u +%FT%TZ) cache dir absent at $CACHE_DIR — nothing to prune"
    exit 0
fi

echo "$(date -u +%FT%TZ) starting npm cache prune"
du -sh "$CACHE_DIR" 2>/dev/null | sed 's/^/before: /'

# Detect whether atime is being updated on this mount. We touch a probe file,
# read it, then re-stat: if atime did not advance, the mount is `noatime` and
# we must fall back to mtime.
TIME_FLAG="-atime"
PROBE="$(mktemp -p "$CACHE_DIR" .atime-probe.XXXXXX 2>/dev/null || true)"
if [ -n "${PROBE:-}" ] && [ -f "$PROBE" ]; then
    # Backdate atime by 1 day. GNU and BSD `date` differ; try GNU first.
    backdated="$(date -u -d '1 day ago' '+%Y%m%d%H%M' 2>/dev/null \
                 || date -u -v-1d '+%Y%m%d%H%M' 2>/dev/null \
                 || echo "")"
    if [ -n "$backdated" ]; then
        touch -a -t "$backdated" "$PROBE" 2>/dev/null || true
        before_atime=$(stat -c %X "$PROBE" 2>/dev/null || echo 0)
        cat "$PROBE" >/dev/null 2>&1 || true
        after_atime=$(stat -c %X "$PROBE" 2>/dev/null || echo 0)
        if [ "$after_atime" -le "$before_atime" ]; then
            echo "WARN: atime not advancing on $CACHE_DIR (likely noatime mount) — falling back to mtime"
            TIME_FLAG="-mtime"
        fi
    fi
    rm -f "$PROBE"
fi

find "$CACHE_DIR" -type f "$TIME_FLAG" +7 -delete 2>/dev/null || true

verify_rc=0
if command -v npm >/dev/null 2>&1; then
    set +o pipefail
    npm cache verify 2>&1 | sed 's/^/verify: /'
    verify_rc=${PIPESTATUS[0]}
    set -o pipefail
    if [ "$verify_rc" -ne 0 ]; then
        echo "WARN: npm cache verify exited $verify_rc"
    fi
else
    echo "npm not on PATH — skipping verify"
fi

du -sh "$CACHE_DIR" 2>/dev/null | sed 's/^/after:  /'
echo "$(date -u +%FT%TZ) done"
exit "$verify_rc"
