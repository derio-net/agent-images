# Agent Pod Restart Resilience — Implementation Plan (agent-images side)

**Spec:** `derio-net/frank:docs/superpowers/specs/2026-04-27--agents--restart-resilience-design.md`
**Status:** Complete

**Type:** Foundation extension of the agent-images repo. Companion to the spec in `derio-net/frank` (linked above) and the [frank-side plan](https://github.com/derio-net/frank/blob/main/docs/superpowers/plans/2026-04-27--agents--restart-resilience.md) which handles the cluster-side work (notifications + cutover + verification).

**Goal:** Build the image foundation that lets the secure-agent-pod (and the planned fleet of sibling agent pods) survive container restarts gracefully. Specifically: introduce `agent-shell-base` (s6-overlay v3 + supervised sshd/supercronic + tmux-resurrect/continuum + parameterized AGENT_USER/AGENT_HOME), migrate secure-agent-kali to use it, and give vk-local consistent first-boot setup without subjecting it to s6 (vibe-kanban stays a single-driver-process container under K8s supervision).

**Why now:** Two real failures on 2026-04-26/27 (in-pod agent SIGHUP'd supercronic via `wait -n` → kali container died; image bump 4.5h later silently recreated the pod) made the cost of the current design concrete. PR #127 in frank shipped operator-side mitigation (wezterm Cmd+Shift+{1,2} re-spawn); this plan addresses the underlying disruption.

**Cross-repo coordination:**
- This plan covers Phases 1-4 (image work) — must complete and produce new GHCR image SHAs before the frank-side cutover (frank plan's Phase 2)
- The frank-side plan covers Phases 5-9 (cluster-side) — its Phase 1 (ArgoCD Notifications) can land in parallel with this plan's Phases 1-4
- After the four PRs in this repo merge, the bumper workflow auto-fires PRs in `derio-net/frank`. Hold those bump PRs until all four phases here have landed; then the frank plan's Phase 2 picks up the merge

---

## Phase 1: `/opt/agent-init.d/` shared first-boot scripts in `agent-base` [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/16 -->
**Depends on:** —

<!-- Tracking: Add scripts to agent-base; both kali (via agent-shell-base) and vk-local (via direct entrypoint) consume them. -->

Move the first-boot setup that's currently inline in `kali/entrypoint.sh` into a per-repo location both children can call. Scripts must be idempotent (every boot) and safe to call as the non-root agent user.

### Task 1: Add `/opt/agent-init.d/01-pvc-dirs` to `agent-base/`

- [x] **Step 1: Create `agent-base/opt/agent-init.d/01-pvc-dirs` script**

```bash
#!/bin/bash
# 01-pvc-dirs — Create PVC-backed directories with correct permissions.
# Idempotent: every-boot script. Uses $AGENT_HOME (set in agent-base ENV).
set -e
HOME="${AGENT_HOME:-$HOME}"
mkdir -p "$HOME/.ssh-host-keys" "$HOME/.ssh" "$HOME/repos" "$HOME/.claude" "$HOME/.willikins-agent"
chmod 700 "$HOME/.ssh-host-keys" "$HOME/.ssh"
```

- [x] **Step 2: Add to `agent-base/Dockerfile`**

```dockerfile
COPY opt/agent-init.d/ /opt/agent-init.d/
RUN chmod +x /opt/agent-init.d/*
```

### Task 2: Add `/opt/agent-init.d/02-credential-migrate`

- [x] **Step 1: Create `agent-base/opt/agent-init.d/02-credential-migrate` script**

Migrates the legacy gitconfig credential helper from env-var-based (which silently failed for VS Code subprocesses and cron) to `/proc/1/environ` reader. Lifted from current `kali/entrypoint.sh` lines covering this migration. Use `$AGENT_HOME`, not `/home/claude`.

```bash
#!/bin/bash
# 02-credential-migrate — Migrate legacy gitconfig credential helper to /proc/1/environ.
set -e
HOME="${AGENT_HOME:-$HOME}"
[ -f /opt/gitconfig ] || exit 0
[ -f "$HOME/.gitconfig" ] || exit 0
if grep -qF 'password=$GITHUB_TOKEN' "$HOME/.gitconfig"; then
    echo "[agent-init] migrating git credential helper to /proc/1/environ reader"
    cp /opt/gitconfig "$HOME/.gitconfig"
fi
```

### Task 3: Add `/opt/agent-init.d/03-credential-scrub`

- [x] **Step 1: Create `agent-base/opt/agent-init.d/03-credential-scrub` script**

Removes leaked git credentials from PVC state (URL `.insteadof` rewrites, embedded-token origin URLs). Lifted from current `kali/entrypoint.sh`. Idempotent — runs every boot.

```bash
#!/bin/bash
# 03-credential-scrub — Strip leaked tokens from PVC-resident git config.
set -e
HOME="${AGENT_HOME:-$HOME}"

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
        echo "[agent-init] scrubbed credentials from $(basename "$repo_dir") origin"
    fi
done
shopt -u nullglob
```

### Task 4: Validate scripts work standalone

- [x] **Step 1: Build agent-base locally and exercise the scripts**

```bash
docker build -t agent-base:test ./agent-base
docker run --rm -e AGENT_HOME=/tmp/test-home -e HOME=/tmp/test-home agent-base:test \
    bash -c 'mkdir -p /tmp/test-home && for s in /opt/agent-init.d/*; do echo "==> $s"; "$s"; done'
```

Expected: each script runs to completion with exit 0. The `01-pvc-dirs` script creates the expected dirs. `02-credential-migrate` and `03-credential-scrub` are no-ops on the empty test home.

### Task 5: Open PR + merge

- [x] **Step 1: Open PR `feat(base): /opt/agent-init.d shared first-boot scripts`**

Body explains the role: shared first-boot setup that both `agent-shell-base`-derived images (via `cont-init.d`) and `vk-local` (via entrypoint wrapper) call. No behavior change to existing children yet — kali still has its own entrypoint that doesn't call these. Phase 3 cuts kali over.

- [x] **Step 2: Wait for matrix CI green, then merge**

CI builds agent-base + secure-agent-kali + vk-local on every push. Confirm all three still build. The bumper workflow will fire a chore PR in frank — **do not merge it yet** until Phase 4 lands. Hold or close the bump PR.

---

## Phase 2: Build `agent-shell-base` image [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/17 -->
**Depends on:** Phase 1

<!-- Tracking: New base image with s6-overlay v3 + supervised sshd/supercronic + tmux-resurrect/continuum + parameterization. -->

Net-new Dockerfile + cont-init.d + services.d + cont-finish.d + tmux-plugin install. Builds once in agent-images CI; no children depend on it yet (Phase 3 cuts kali over).

### Task 1: Scaffold `agent-shell-base/` directory in `agent-images`

- [x] **Step 1: Create the directory layout**

```text
agent-shell-base/
├── Dockerfile
├── sshd_config
├── etc/
│   ├── cont-init.d/
│   │   ├── 00-run-agent-init
│   │   ├── 10-ssh-host-keys
│   │   ├── 20-venv
│   │   └── 30-authorized-keys
│   ├── services.d/
│   │   ├── sshd/
│   │   │   ├── run
│   │   │   └── finish
│   │   └── supercronic/
│   │       ├── run
│   │       └── finish
│   ├── cont-finish.d/
│   │   ├── 01-shutdown
│   │   └── 02-tmux-save
│   ├── skel/
│   │   └── .tmux.conf
│   └── agent/
│       └── tmux-resurrect.conf
└── README.md
```

### Task 2: Write `agent-shell-base/Dockerfile`

- [x] **Step 1: s6-overlay install + parameterization**

```dockerfile
ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-base:${BASE_SHA}

ARG AGENT_USER=agent
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG AGENT_HOME=/home/agent
ENV AGENT_USER=${AGENT_USER} AGENT_UID=${AGENT_UID} AGENT_HOME=${AGENT_HOME}

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server \
      tmux mosh locales-all \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /var/run/sshd

ARG SUPERCRONIC_VERSION=0.2.30
RUN curl -fsSLo /usr/local/bin/supercronic \
      https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-amd64 \
    && chmod +x /usr/local/bin/supercronic

RUN mkdir -p /usr/local/share/tmux-plugins \
    && git clone --depth 1 https://github.com/tmux-plugins/tmux-resurrect /usr/local/share/tmux-plugins/tmux-resurrect \
    && git clone --depth 1 https://github.com/tmux-plugins/tmux-continuum /usr/local/share/tmux-plugins/tmux-continuum

ARG S6_OVERLAY_VERSION=3.2.0.2
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp/
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz \
    && rm /tmp/s6-overlay-*.tar.xz

ENV S6_KEEP_ENV=1 \
    S6_VERBOSITY=2 \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_KILL_GRACETIME=10000

RUN groupadd --gid ${AGENT_GID} ${AGENT_USER} \
    && useradd --uid ${AGENT_UID} --gid ${AGENT_GID} \
               --create-home --home-dir ${AGENT_HOME} \
               --shell /bin/bash ${AGENT_USER}

COPY etc/ /etc/
RUN chmod +x /etc/cont-init.d/* /etc/services.d/*/run /etc/services.d/*/finish /etc/cont-finish.d/*

COPY sshd_config /opt/sshd_config
RUN sed -i "s|__AGENT_HOME__|${AGENT_HOME}|g" /opt/sshd_config

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}

ENTRYPOINT ["/init"]
```

### Task 3: Write `etc/cont-init.d/00-run-agent-init`

- [x] **Step 1: Wrapper that calls all scripts in `/opt/agent-init.d/` in order**

```bash
#!/usr/bin/with-contenv bash
# 00-run-agent-init — Call shared first-boot scripts from agent-base.
set -e
shopt -s nullglob
for s in /opt/agent-init.d/*; do
    [ -x "$s" ] || continue
    echo "[cont-init] running $s"
    "$s"
done
```

`with-contenv` passes Docker env vars (including `$AGENT_HOME`) into the script — required for non-root mode.

### Task 4: Write `etc/cont-init.d/10-ssh-host-keys`

- [x] **Step 1: Generate sshd host keys on first boot, idempotent**

```bash
#!/usr/bin/with-contenv bash
set -e
KEYDIR="${AGENT_HOME}/.ssh-host-keys"
if [ ! -f "$KEYDIR/ssh_host_ed25519_key" ]; then
    echo "[cont-init] generating SSH host keys (first boot)"
    ssh-keygen -t ed25519 -f "$KEYDIR/ssh_host_ed25519_key" -N ""
    ssh-keygen -t rsa -b 4096 -f "$KEYDIR/ssh_host_rsa_key" -N ""
fi
chmod 600 "$KEYDIR"/ssh_host_*_key
```

### Task 5: Write `etc/cont-init.d/20-venv`

- [x] **Step 1: Create uv venv with croniter for cron-monitor scripts**

```bash
#!/usr/bin/with-contenv bash
# 20-venv — Python venv for cron heartbeat scripts (compute-next-run.py,
# push-next-expected.sh use croniter).
set -e
VENV="${AGENT_HOME}/.willikins-agent/.venv"
if [ ! -d "$VENV" ]; then
    echo "[cont-init] creating Python venv for cron monitor scripts"
    mkdir -p "${AGENT_HOME}/.willikins-agent"
    uv venv "$VENV"
    uv pip install --python "$VENV/bin/python" croniter
fi
```

### Task 6: Write `etc/cont-init.d/30-authorized-keys`

- [x] **Step 1: Copy authorized_keys from mounted Secret to $AGENT_HOME/.ssh/**

```bash
#!/usr/bin/with-contenv bash
set -e
if [ -f /etc/ssh-keys/authorized_keys ]; then
    cp /etc/ssh-keys/authorized_keys "${AGENT_HOME}/.ssh/authorized_keys"
    chmod 600 "${AGENT_HOME}/.ssh/authorized_keys"
fi
```

### Task 7: Write `etc/services.d/sshd/{run,finish}`

- [x] **Step 1: sshd service definition**

`run`:
```bash
#!/usr/bin/with-contenv bash
exec /usr/sbin/sshd -f /opt/sshd_config -D -e
```

`finish`:
```bash
#!/usr/bin/with-contenv bash
echo "[s6] sshd exited code=$1 (signal=$2)"
exit 0
```

### Task 8: Write `etc/services.d/supercronic/{run,finish}`

- [x] **Step 1: supercronic service definition**

`run`:
```bash
#!/usr/bin/with-contenv bash
exec supercronic "${AGENT_HOME}/.crontab"
```

`finish`:
```bash
#!/usr/bin/with-contenv bash
echo "[s6] supercronic exited code=$1 (signal=$2)"
exit 0
```

### Task 9: Write `etc/cont-finish.d/{01-shutdown, 02-tmux-save}`

- [x] **Step 1: 01-shutdown — calls per-pod shutdown.sh if present**

```bash
#!/usr/bin/with-contenv bash
set +e
if [ -x /opt/scripts/shutdown.sh ]; then
    echo "[cont-finish] running /opt/scripts/shutdown.sh"
    /opt/scripts/shutdown.sh
fi
exit 0
```

- [x] **Step 2: 02-tmux-save — force tmux-resurrect save before shutdown**

```bash
#!/usr/bin/with-contenv bash
set +e
if pgrep -u "${AGENT_USER}" tmux >/dev/null 2>&1; then
    echo "[cont-finish] forcing tmux-resurrect save before shutdown"
    su - "${AGENT_USER}" -c 'tmux run-shell /usr/local/share/tmux-plugins/tmux-resurrect/scripts/save.sh' || true
fi
exit 0
```

### Task 10: Write `etc/skel/.tmux.conf` baseline

- [x] **Step 1: Baseline seeded into $AGENT_HOME on first boot**

```text
# Baseline tmux config — seeded from /etc/skel into $AGENT_HOME on first boot.
# Subsequent boots leave any operator customizations alone.

set -g default-terminal "tmux-256color"
set -g mouse on
set -g history-limit 100000
set -g status-right "#{?client_prefix,#[bg=red,bold] PREFIX ,}#H:#M"

bind | split-window -h \; select-layout even-horizontal
bind S split-window -v \; select-layout even-vertical
bind r source-file ~/.tmux.conf \; display "reloaded"

source-file /etc/agent/tmux-resurrect.conf
```

### Task 11: Write `etc/agent/tmux-resurrect.conf`

- [x] **Step 1: Plugin loader + settings — sourced by .tmux.conf**

```text
set -g @resurrect-dir '~/.tmux/resurrect'
set -g @resurrect-capture-pane-contents 'on'

set -g @continuum-save-interval '5'
set -g @continuum-restore 'on'

run-shell /usr/local/share/tmux-plugins/tmux-resurrect/resurrect.tmux
run-shell /usr/local/share/tmux-plugins/tmux-continuum/continuum.tmux
```

### Task 12: Write baseline `sshd_config`

- [x] **Step 1: Non-root sshd config with __AGENT_HOME__ placeholders**

```text
Port 2222
HostKey __AGENT_HOME__/.ssh-host-keys/ssh_host_ed25519_key
HostKey __AGENT_HOME__/.ssh-host-keys/ssh_host_rsa_key
AuthorizedKeysFile __AGENT_HOME__/.ssh/authorized_keys
PubkeyAuthentication yes
PasswordAuthentication no
UsePAM no
StrictModes no
PidFile __AGENT_HOME__/.ssh/sshd.pid
```

The Dockerfile's `RUN sed` substitutes `__AGENT_HOME__` with the actual `$AGENT_HOME` value at build time.

### Task 13: Add agent-shell-base to CI matrix

- [x] **Step 1: Update `.github/workflows/build.yml` matrix**

Add `agent-shell-base` to the matrix list. Build order: agent-base → agent-shell-base (uses `BASE_SHA` arg from agent-base's just-built tag) → kali/vk-local.

### Task 14: Build smoke test

- [x] **Step 1: Local container exercises s6 + sshd + supercronic + crashloop bail**

```bash
docker build -t agent-shell-base:test \
    --build-arg BASE_SHA=$(git rev-parse HEAD) \
    ./agent-shell-base

docker run -d --name shell-test \
    --user 1000 \
    --cap-drop ALL \
    -v $(pwd)/test-home:/home/agent \
    -p 2222:2222 \
    agent-shell-base:test

sleep 3

docker exec shell-test s6-svstat /run/service/sshd
docker exec shell-test s6-svstat /run/service/supercronic
docker exec shell-test pgrep -af supercronic
docker exec shell-test pgrep -af 'sshd: /usr/sbin'

# Single transient flap — observe respawn within 1-2s.
docker exec shell-test pkill -SIGTERM supercronic
sleep 2
docker exec shell-test s6-svstat /run/service/supercronic

# Crashloop bail — 5 deaths in 60s.
for i in 1 2 3 4 5 6; do
    docker exec shell-test pkill -SIGKILL supercronic 2>/dev/null
    sleep 0.5
done
sleep 5
docker exec shell-test s6-svstat /run/service/supercronic   # down
docker exec shell-test s6-svstat /run/service/sshd          # still up

docker rm -f shell-test
```

Expected: respawn works for single flap; bail-out triggers after 5 deaths in 60s; sshd unaffected by supercronic bail.

### Task 15: Open PR + merge

- [x] **Step 1: Open PR `feat(images): agent-shell-base — s6-overlay supervisor + tmux persistence`**

- [x] **Step 2: Wait for matrix CI green, merge**

Bumper fires for kali + vk-local with the new agent-base SHA — **still hold those bumps** until Phase 4 lands.

---

## Phase 3: Migrate `secure-agent-kali` to `FROM agent-shell-base` [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/18 -->
**Depends on:** Phase 2

<!-- Tracking: Cut kali over to s6-based shell-base; preserve claude/home/claude state via build args; delete bespoke entrypoint.sh. -->

The migration that actually delivers the resilience to the running pod. Kali keeps its identity (`claude`/`/home/claude`) via build args; everything else (sshd, supercronic, tmux, /opt/scripts/, /opt/crontab) stays.

### Task 1: Update `kali/Dockerfile` to FROM agent-shell-base

- [x] **Step 1: Change FROM line, override agent identity, drop entrypoint logic**

```dockerfile
ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}

# Preserve existing PV state: stay as `claude` / `/home/claude`.
ARG AGENT_USER=claude
ARG AGENT_HOME=/home/claude
USER root

# agent-shell-base created `agent` user; replace with legacy identity.
RUN userdel -r agent 2>/dev/null || true \
    && groupadd --gid 1000 ${AGENT_USER} \
    && useradd --uid 1000 --gid 1000 \
               --create-home --home-dir ${AGENT_HOME} \
               --shell /bin/bash ${AGENT_USER}

ENV AGENT_USER=${AGENT_USER} AGENT_HOME=${AGENT_HOME}

# Re-substitute sshd_config for the legacy home.
RUN sed -i "s|/home/agent|${AGENT_HOME}|g" /opt/sshd_config

# Kali repos + tools (existing).
RUN apt-get update && apt-get install -y --no-install-recommends \
      kali-archive-keyring \
    && echo "deb https://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware" > /etc/apt/sources.list.d/kali.list \
    && apt-get update && apt-get install -y --no-install-recommends \
       kali-tools-top10 nmap netcat-traditional logrotate \
    && rm -rf /var/lib/apt/lists/*

# Existing /opt/scripts/, /opt/crontab, /opt/load-env.sh, /opt/bashrc,
# /opt/settings.json, /opt/gitconfig — UNCHANGED, copied as before.
COPY opt/ /opt/

# Existing CLI installs (kubectl, talosctl, omnictl, claude, gh, ...) —
# UNCHANGED; copy from current Dockerfile lines.

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}

# ENTRYPOINT inherited from agent-shell-base ("/init"). Do NOT override.
```

### Task 2: Delete `kali/entrypoint.sh`

- [x] **Step 1: Remove the file**

Its responsibilities migrated to:
- First-boot dirs/configs → `/opt/agent-init.d/01-pvc-dirs` (Phase 1)
- Credential migration/scrub → `/opt/agent-init.d/02-credential-migrate`, `03-credential-scrub` (Phase 1)
- ssh host keys → `/etc/cont-init.d/10-ssh-host-keys` (Phase 2)
- venv creation → `/etc/cont-init.d/20-venv` (Phase 2)
- authorized_keys → `/etc/cont-init.d/30-authorized-keys` (Phase 2)
- sshd start → `/etc/services.d/sshd/run` (Phase 2)
- supercronic start → `/etc/services.d/supercronic/run` (Phase 2)
- SIGTERM trap → handled by s6
- shutdown.sh → `/etc/cont-finish.d/01-shutdown` calls `/opt/scripts/shutdown.sh`
- `wait -n` → not needed; s6 supervises

### Task 3: Audit `/opt/scripts/*.sh` for hardcoded /home/claude paths

- [x] **Step 1: Grep + replace**

```bash
grep -rnE '/home/claude' kali/opt/scripts/
```

Most current scripts use `${WILLIKINS_AGENT_DIR:-$HOME/.willikins-agent}` or similar — these are clean. Any hardcoded `/home/claude` references must be replaced with `$HOME` or `$AGENT_HOME` even though kali stays as `claude` today. **Required cleanup before merge** — hardcoded paths block the future rename plan.

### Task 4: Smoke test the migrated image

- [-] **Step 1: Build with explicit build args** <!-- CI smoke tests cover this -->

```bash
docker build -t secure-agent-kali:test \
    --build-arg BASE_SHA=$(git rev-parse HEAD) \
    --build-arg AGENT_USER=claude \
    --build-arg AGENT_HOME=/home/claude \
    ./kali
```

- [-] **Step 2: Run with the same SecurityContext as the deployment** <!-- CI smoke tests cover this -->

```bash
docker run -d --name kali-test \
    --user 1000 \
    --cap-drop ALL \
    -v $(pwd)/test-home:/home/claude \
    -p 2222:2222 \
    secure-agent-kali:test

sleep 3
docker exec kali-test id
docker exec kali-test ls /home/claude/.ssh-host-keys/ssh_host_ed25519_key
docker exec kali-test pgrep -af 'sshd: /usr/sbin'
docker exec kali-test pgrep -af supercronic
docker exec kali-test ls /usr/local/share/tmux-plugins/

ssh -p 2222 -i test-key claude@127.0.0.1 'whoami'   # claude

docker rm -f kali-test
```

### Task 5: Open PR + merge

- [x] **Step 1: Open PR `feat(kali): migrate to agent-shell-base; delete entrypoint.sh`**

- [ ] **Step 2: Wait for matrix CI green, merge**

Bumper fires; **STILL hold the bump** in frank until Phase 4 lands. Bundling kali + vk-local in one cutover is cleaner than two consecutive bounces.

---

## Phase 4: `vk-local` entrypoint wrapper [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/19 -->
**Depends on:** Phase 1

<!-- Tracking: Add wrapper that runs /opt/agent-init.d/* before exec'ing vibe-kanban. No s6, no supervisor — vibe-kanban stays the driver process under tini's PID 1. Parallel with Phases 2-3 (only blocks on Phase 1's init.d scripts). -->

Minimal change: vk-local gains shared first-boot setup consistency; doesn't gain s6 (would invert K8s health contract for the driver process).

### Task 1: Add `vk-local/entrypoint-vk-local.sh`

- [ ] **Step 1: Thin wrapper script**

```bash
#!/bin/sh
# entrypoint-vk-local.sh — Run shared first-boot scripts, then exec vibe-kanban.
# vibe-kanban remains the driver process under tini's PID 1; K8s supervises.
set -e

shopt -s nullglob 2>/dev/null || true
for s in /opt/agent-init.d/*; do
    [ -x "$s" ] && "$s"
done

exec vibe-kanban "$@"
```

### Task 2: Update `vk-local/Dockerfile`

- [ ] **Step 1: Add wrapper, set ENTRYPOINT through tini**

```dockerfile
# (existing FROM agent-base + COPY of vibe-kanban binary, etc.)

COPY entrypoint-vk-local.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
```

### Task 3: Smoke test vk-local

- [ ] **Step 1: Build + run + verify vibe-kanban starts and serves /api/health**

```bash
docker build -t vk-local:test --build-arg BASE_SHA=$(git rev-parse HEAD) ./vk-local
docker run -d --name vk-test \
    --user 1000 \
    -v $(pwd)/test-home:/home/claude \
    -p 8081:8081 \
    -e PORT=8081 -e HOST=0.0.0.0 \
    vk-local:test

sleep 5
curl -fsS http://127.0.0.1:8081/api/health   # 200 OK
docker exec vk-test ls /home/claude/repos    # dir exists (created by 01-pvc-dirs)
docker rm -f vk-test
```

### Task 4: Open PR + merge

- [ ] **Step 1: Open PR `feat(vk-local): wrapper runs /opt/agent-init.d/* before vibe-kanban`**

- [ ] **Step 2: Wait for matrix CI green, merge**

After this merges, the bumper has accumulated 4 changes (Phases 1-4). Either let it open one combined bump PR for frank, or open one explicitly with all SHAs. The frank-side plan picks up from there with its Phase 2 (cutover).

---

## Out of scope (deliberately)

- secure-agent-kali rename to `agent`/`/home/agent` — separate plan
- Tmux usage inside vk-local — VK-side decision; out of scope here
- Per-pod egress profiles for new shell pods — per-pod plans (in their own time)
- Service dependencies (s6-rc) for credential-mount-ready ordering — when needed

---

## Post-deploy deviations

### 2026-05-02 — `/run` ownership regression under K8s securityContext

**Symptom:** After `frank` PR #166 (auto-bumper) promoted `secure-agent-pod` to image SHA `3fdae2b…`, the kali container hit `CrashLoopBackOff` with:

```
/package/admin/s6-overlay/libexec/preinit: fatal: /run belongs to uid 0
   instead of 1000 and we're lacking the privileges to fix it.
s6-overlay-suexec: fatal: child failed with exit code 100
```

**Root cause:** `agent-shell-base/Dockerfile` chowned the *subdirectories* it created under `/run` (`/run/service`, `/run/s6`, `/run/s6-rc`, `/run/sshd`, `/var/run/s6`, `/var/run/sshd`) but not `/run` and `/var/run` themselves. s6-overlay v3's preinit needs to create new entries directly under `/run` (e.g. `/run/s6/container_environment`, `/run/s6-linux-init-container-results`). With the K8s pod's `allowPrivilegeEscalation: false` + `capabilities.drop=["ALL"]`, `s6-overlay-suexec` cannot self-elevate to chown `/run`, so preinit bails.

**Why CI didn't catch it:** the only smoke test (`smoke-test-vk-local`, added in PR #40) targets `vk-local`, which has no s6 supervisor, and uses `--entrypoint /bin/sh` to bypass `/init` entirely. The kali path never ran under K8s-equivalent constraints in CI, so the missing chown surfaced only on live deploy.

**Fix (three sequential PRs, each unmasked by the previous one):**

1. **PR #41 — `fix(agent-shell-base): chown /run + /var/run for s6-overlay non-root preinit`** — addresses the root cause above.
   - `agent-shell-base/Dockerfile`: replace `chown -R … /run/service /run/s6 …` with `chown -R … /run /var/run` so `/run` itself is agent-owned and preinit's writes succeed.
   - `.github/workflows/build.yaml`: add `smoke-test-secure-agent-kali` job that boots `/init` with `--user 1000:1000 --cap-drop=ALL --security-opt=no-new-privileges`, mirroring the live pod's securityContext, and waits for `s6-svstat /run/service/sshd` to report `up`. Regression-tests this exact failure mode.

2. **PR #42 — `fix(agent-shell-base): with-contenv shebang must be /command/with-contenv`** — uncovered immediately by #41's new smoke test. Every cont-init.d / cont-finish.d / services.d script used `#!/usr/bin/with-contenv bash`, but s6-overlay v3 only installs `with-contenv` under `/command/` (not `/usr/bin/`), so all 12 supervised scripts exited 127 on the interpreter, dragging legacy-cont-init to "unable to start" and a fatal `rc.init: stopping the container`. Latent since the Phase 3 migration; masked by #41's preinit failure. Fixed all 12 files to `#!/command/with-contenv bash`.

3. **PR #43 — `fix(ci): smoke-test must call s6-svstat by full /command/ path`** — uncovered after #42 made the supervisor actually start. The smoke test's `docker exec kali-smoke s6-svstat …` was failing silently with ENOENT (`/command/` not on agent-base PATH; `2>/dev/null` suppressed the error), so the 30s loop never matched even though sshd and supercronic were healthy. Switched to `/command/s6-svstat` so the regression net actually closes.

**Outcome:** Image SHA `c804fab75ba1a4f71fe8b597f3d6e9d08d862e43` (post-#43) bumped into frank via PR #168; ArgoCD synced; pod `secure-agent-pod-56874b8f5d-*` came up clean (0 restarts, sshd + supercronic both `up` per `s6-svstat`). Gotchas in `frank:.claude/rules/frank-gotchas.md` cover both the `/run` chown requirement and the `with-contenv` shebang path. **Resolved.**

**Lessons recorded for future s6-overlay-style migrations:**
- A new image lineage with a new init system (s6-overlay vs. tini) MUST get its own end-to-end smoke test exercising `/init` under K8s-equivalent securityContext (`--cap-drop=ALL --security-opt=no-new-privileges`) before being promoted by an auto-bumper. The vk-local-only smoke test predating Phase 3 was structurally unable to catch any kali-side regression.
- Latent bugs stack. The `/run` chown failure masked the shebang failure, which masked the smoke-test-path failure. Each fix unblocked the next. Plan for two-to-three iterations when reviving an image chain that's been broken for a while.
- `2>/dev/null` in smoke tests should be used surgically. Suppressing all stderr around a probe converts a "command not found" into a successful "wait longer" — exactly the wrong behavior.
