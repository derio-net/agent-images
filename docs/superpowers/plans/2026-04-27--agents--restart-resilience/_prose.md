# Agent Pod Restart Resilience — Implementation Plan (agent-images side)

## Phase 1: `/opt/agent-init.d/` shared first-boot scripts in `agent-base`

### Task 1: Add `/opt/agent-init.d/01-pvc-dirs` to `agent-base/`

- P1.T1.S1: Create `agent-base/opt/agent-init.d/01-pvc-dirs` script

- P1.T1.S2: Add to `agent-base/Dockerfile`

### Task 2: Add `/opt/agent-init.d/02-credential-migrate`

- P1.T2.S1: Create `agent-base/opt/agent-init.d/02-credential-migrate` script

### Task 3: Add `/opt/agent-init.d/03-credential-scrub`

- P1.T3.S1: Create `agent-base/opt/agent-init.d/03-credential-scrub` script

### Task 4: Validate scripts work standalone

- P1.T4.S1: Build agent-base locally and exercise the scripts

### Task 5: Open PR + merge

- P1.T5.S1: Open PR `feat(base): /opt/agent-init.d shared first-boot scripts`

- P1.T5.S2: Wait for matrix CI green, then merge

## Phase 2: Build `agent-shell-base` image

### Task 1: Scaffold `agent-shell-base/` directory in `agent-images`

- P2.T1.S1: Create the directory layout

### Task 2: Write `agent-shell-base/Dockerfile`

- P2.T2.S1: s6-overlay install + parameterization

### Task 3: Write `etc/cont-init.d/00-run-agent-init`

- P2.T3.S1: Wrapper that calls all scripts in `/opt/agent-init.d/` in order

### Task 4: Write `etc/cont-init.d/10-ssh-host-keys`

- P2.T4.S1: Generate sshd host keys on first boot, idempotent

### Task 5: Write `etc/cont-init.d/20-venv`

- P2.T5.S1: Create uv venv with croniter for cron-monitor scripts

### Task 6: Write `etc/cont-init.d/30-authorized-keys`

- P2.T6.S1: Copy authorized_keys from mounted Secret to $AGENT_HOME/.ssh/

### Task 7: Write `etc/services.d/sshd/{run,finish}`

- P2.T7.S1: sshd service definition

### Task 8: Write `etc/services.d/supercronic/{run,finish}`

- P2.T8.S1: supercronic service definition

### Task 9: Write `etc/cont-finish.d/{01-shutdown, 02-tmux-save}`

- P2.T9.S1: 01-shutdown — calls per-pod shutdown.sh if present

- P2.T9.S2: 02-tmux-save — force tmux-resurrect save before shutdown

### Task 10: Write `etc/skel/.tmux.conf` baseline

- P2.T10.S1: Baseline seeded into $AGENT_HOME on first boot

### Task 11: Write `etc/agent/tmux-resurrect.conf`

- P2.T11.S1: Plugin loader + settings — sourced by .tmux.conf

### Task 12: Write baseline `sshd_config`

- P2.T12.S1: Non-root sshd config with __AGENT_HOME__ placeholders

### Task 13: Add agent-shell-base to CI matrix

- P2.T13.S1: Update `.github/workflows/build.yml` matrix

### Task 14: Build smoke test

- P2.T14.S1: Local container exercises s6 + sshd + supercronic + crashloop bail

### Task 15: Open PR + merge

- P2.T15.S1: Open PR `feat(images): agent-shell-base — s6-overlay supervisor + tmux persistence`

- P2.T15.S2: Wait for matrix CI green, merge

## Phase 3: Migrate `secure-agent-kali` to `FROM agent-shell-base`

### Task 1: Update `kali/Dockerfile` to FROM agent-shell-base

- P3.T1.S1: Change FROM line, override agent identity, drop entrypoint logic

### Task 2: Delete `kali/entrypoint.sh`

- P3.T2.S1: Remove the file

### Task 3: Audit `/opt/scripts/*.sh` for hardcoded /home/claude paths

- P3.T3.S1: Grep + replace

### Task 4: Smoke test the migrated image

- P3.T4.S1: Build with explicit build args <!-- CI smoke tests cover this -->

- P3.T4.S2: Run with the same SecurityContext as the deployment <!-- CI smoke tests cover this -->

### Task 5: Open PR + merge

- P3.T5.S1: Open PR `feat(kali): migrate to agent-shell-base; delete entrypoint.sh`

- P3.T5.S2: Wait for matrix CI green, merge

## Phase 4: `vk-local` entrypoint wrapper

### Task 1: Add `vk-local/entrypoint-vk-local.sh`

- P4.T1.S1: Thin wrapper script

### Task 2: Update `vk-local/Dockerfile`

- P4.T2.S1: Add wrapper, set ENTRYPOINT through tini

### Task 3: Smoke test vk-local

- P4.T3.S1: Build + run + verify vibe-kanban starts and serves /api/health

### Task 4: Open PR + merge

- P4.T4.S1: Open PR `feat(vk-local): wrapper runs /opt/agent-init.d/* before vibe-kanban`

- P4.T4.S2: Wait for matrix CI green, merge
