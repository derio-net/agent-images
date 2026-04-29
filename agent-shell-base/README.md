# agent-shell-base

Intermediate Docker image that adds s6-overlay v3 supervision, sshd, supercronic, and tmux-resurrect/continuum on top of `agent-base`.

## What's included

- **s6-overlay v3** — PID 1 init + service supervisor
- **sshd** — supervised on port 2222; host keys generated on first boot to PVC
- **supercronic** — supervised cron replacement (from agent-base)
- **tmux-resurrect + tmux-continuum** — session save/restore on shutdown/boot
- **Parameterized identity** — `AGENT_USER`, `AGENT_UID`, `AGENT_GID`, `AGENT_HOME` build args (defaults: `agent`/1000/1000/`/home/agent`)

## Boot sequence

1. s6 runs `cont-init.d/` in order:
   - `00-run-agent-init` — calls `/opt/agent-init.d/*` from agent-base (PVC dirs, credential migration/scrub)
   - `10-ssh-host-keys` — generates SSH host keys into `$AGENT_HOME/.ssh-host-keys/` (first boot only)
   - `20-venv` — creates `$AGENT_HOME/.willikins-agent/.venv` with croniter (first boot only)
   - `30-authorized-keys` — copies `/etc/ssh-keys/authorized_keys` → `$AGENT_HOME/.ssh/`
2. s6 supervises services (`services.d/`): `sshd` and `supercronic`
3. On shutdown, `cont-finish.d/` runs: calls `shutdown.sh` (if present) + forces tmux-resurrect save

## Usage

Children override identity via build args:

```dockerfile
FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}

ARG AGENT_USER=claude
ARG AGENT_HOME=/home/claude
# ...
ENV AGENT_USER=${AGENT_USER} AGENT_HOME=${AGENT_HOME}
```

`ENTRYPOINT ["/init"]` is inherited — do not override it.
