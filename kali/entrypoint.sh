#!/bin/bash
set -e

# ── First-boot: create directories on PVC with correct permissions ──
mkdir -p "$HOME/.ssh-host-keys" "$HOME/.ssh" "$HOME/repos" "$HOME/.claude" "$HOME/.willikins-agent"
chmod 700 "$HOME/.ssh-host-keys" "$HOME/.ssh"

# ── First-boot: seed config files from /opt/ templates ──
[ -f "$HOME/.crontab" ]              || cp /opt/crontab "$HOME/.crontab"
[ -f "$HOME/.load-env.sh" ]          || cp /opt/load-env.sh "$HOME/.load-env.sh"
[ -f "$HOME/.bashrc" ]               || cp /opt/bashrc "$HOME/.bashrc"
[ -f "$HOME/.claude/settings.json" ] || cp /opt/settings.json "$HOME/.claude/settings.json"
[ -f "$HOME/.gitconfig" ]            || cp /opt/gitconfig "$HOME/.gitconfig"

# ── Migrate legacy gitconfig credential helper (env-var → /proc/1/environ) ──
# The env-var helper only worked when the caller had sourced ~/.bashrc
# (e.g. interactive ssh shells). It silently failed for VS Code's git
# subprocess and cron jobs. The /proc/1/environ helper works regardless.
if [ -f "$HOME/.gitconfig" ] && grep -qF 'password=$GITHUB_TOKEN' "$HOME/.gitconfig"; then
    echo "[agent] migrating git credential helper to /proc/1/environ reader"
    cp /opt/gitconfig "$HOME/.gitconfig"
fi

# ── Every boot: scrub any leaked git credentials from PVC state ──
# Removes url.*@github.com/.insteadof rewrites (which embed tokens on disk)
# and rewrites any ~/repos/* origins that have credentials in the URL.
# Credentials must only be injected at push time via the $GITHUB_TOKEN env var.
while IFS= read -r key; do
    [ -z "$key" ] && continue
    case "$key" in
        *@github.com*) git config --global --unset-all "$key" || true ;;
    esac
done < <(git config --global --name-only --get-regexp '^url\..*\.insteadof$' 2>/dev/null || true)

shopt -s nullglob
for repo_dir in "$HOME"/repos/*/; do
    [ -d "$repo_dir/.git" ] || continue
    origin_url=$(git -C "$repo_dir" remote get-url origin 2>/dev/null) || continue
    clean_url=$(printf '%s' "$origin_url" | sed -E 's#https://[^@/]+@github\.com/#https://github.com/#')
    if [ "$origin_url" != "$clean_url" ]; then
        git -C "$repo_dir" remote set-url origin "$clean_url"
        echo "[agent] scrubbed credentials from $(basename "$repo_dir") origin"
    fi
done
shopt -u nullglob

# ── Generate SSH host keys (first boot only, PVC-backed) ──
if [ ! -f "$HOME/.ssh-host-keys/ssh_host_ed25519_key" ]; then
    echo "[agent] Generating SSH host keys (first boot)..."
    ssh-keygen -t ed25519 -f "$HOME/.ssh-host-keys/ssh_host_ed25519_key" -N ""
    ssh-keygen -t rsa -b 4096 -f "$HOME/.ssh-host-keys/ssh_host_rsa_key" -N ""
fi
chmod 600 "$HOME/.ssh-host-keys"/ssh_host_*_key

# ── First-boot: create Python venv for agent scripts (croniter, etc.) ──
if [ ! -d "$HOME/.willikins-agent/.venv" ]; then
    echo "[agent] Creating Python venv for agent scripts..."
    uv venv "$HOME/.willikins-agent/.venv"
    uv pip install --python "$HOME/.willikins-agent/.venv/bin/python" croniter
fi

# ── Copy authorized_keys from mounted Secret (if present) ──
if [ -f /etc/ssh-keys/authorized_keys ]; then
    cp /etc/ssh-keys/authorized_keys "$HOME/.ssh/authorized_keys"
    chmod 600 "$HOME/.ssh/authorized_keys"
fi

# ── Start sshd in user mode (no root needed) ──
/usr/sbin/sshd -f /opt/sshd_config -D &

# ── Start supercronic (non-root cron) ──
supercronic "$HOME/.crontab" &

echo "[agent] secure-agent-kali ready (sshd on :2222, supercronic active)"

# Wait for any child to exit — if sshd or supercronic dies, pod restarts
wait -n
