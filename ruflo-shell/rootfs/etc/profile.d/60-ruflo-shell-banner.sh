# 60-ruflo-shell-banner.sh — Set ruflo-specific env defaults and print an
# operator-facing banner on SSH login. Sourced after the paths and motd
# drop-ins so PATH and last-reconcile MOTD render first.
#
# LITELLM_BASE_URL is normally set by the pod's Deployment env (see
# apps/ruflo/manifests/deployment.yaml). The default below keeps the env var
# present in `kubectl exec` sessions where the Deployment env may not have
# been propagated, and documents the expected gateway location.

: "${LITELLM_BASE_URL:=http://litellm.litellm-system:4000}"
export LITELLM_BASE_URL

[ -n "$PS1" ] || return 0

if [ -n "${SSH_CONNECTION:-}" ] && [ -z "${RUFLO_BANNER_SHOWN:-}" ]; then
    cat <<'BANNER'
─────────────────────────────────────────
 ruflo-shell — operator side door for ruflo
   /workspace             ← shared with ruvocal (read/write)
   /home/agent            ← yours; persists across pod restarts
   ruflo-shell-reconcile  ← apply inventory changes without restart
─────────────────────────────────────────
BANNER
    export RUFLO_BANNER_SHOWN=1
fi
