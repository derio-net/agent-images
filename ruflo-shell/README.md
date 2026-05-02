# ruflo-shell

SSH-able shell sidecar for the `ruflo` pod on Frank. Built `FROM
agent-shell-base`, adds Layer-1 runtime managers (`mise`, `rustup`, `pipx`)
and a declarative software inventory installer that runs at every container
boot.

The shell pairs with the [`ruflo-server`](../ruflo-server/) container in the
same pod, sharing the `ruflo-workspace` PVC at `/workspace` while keeping its
own home PVC at `/home/agent` for tools, dotfiles, and tmux-resurrect state.
The upstream ruvocal build is **not modified** — `ruflo-server` evolves on the
upstream's cadence; `ruflo-shell` evolves on this repo's cadence.

`@anthropic-ai/claude-code` is baked into the image so the operator can
immediately invoke `claude` against the in-cluster LiteLLM gateway from a
fresh SSH session, before the Layer-2 inventory has run. `claude-flow` is
**not** baked in — it lives in the inventory, where it can be bumped without
rebuilding the image.

## Layered install model

| Layer | Source | Where it lands | When |
|---|---|---|---|
| 1 — Image baseline | this Dockerfile | image rootfs (immutable) | image build |
| 2 — Inventory | mounted ConfigMap `inventory.yaml` | per-user PV under `$HOME` | every container boot via `cont-init.d/40-shell-inventory` |
| 3 — Interactive | operator typing `mise install …`, `cargo install …` | per-user PV under `$HOME` | on demand inside the SSH session |

Layer 2 is the load-bearing one for evolving the toolset. The installer is
idempotent and **fail-open** — a single broken install logs the failure,
fires a Telegram alert via `notify-telegram.sh`, and lets sshd come up
anyway. The MOTD prints the last reconcile summary on every login.

## Inventory file

Mounted from `apps/ruflo/manifests/configmap-shell-inventory.yaml` (in
`derio-net/frank`) at `/etc/ruflo-shell/inventory.yaml`:

```yaml
mise:
  - python@3.12
  - node@20
  - rust@stable
npm-global:
  - claude-flow@alpha
pipx:
  - black
  - ruff
cargo:
  - ripgrep
  - eza
removed:
  mise: []
  npm-global: []
  pipx: []
  cargo: []
```

Top-level keys are managers; entries under `removed.<manager>` are actively
uninstalled. `npm-global` and `cargo` sections are skipped silently if the
underlying runtime (node, rust toolchain) is not yet present — install via
`mise` first.

## Operator commands

```bash
# Re-run the inventory installer without restarting the pod
ruflo-shell-reconcile

# Read the last reconcile log
cat /var/log/cont-init.d/40-shell-inventory.log

# Read the MOTD that prints on every login
cat /var/lib/ruflo-shell/last-reconcile.motd
```

## Build args

| Arg | Default | Notes |
|---|---|---|
| `BASE_SHA` | `latest` | The `agent-shell-base` tag/SHA to inherit from. CI passes the SHA of the same workflow run. |

`AGENT_USER`, `AGENT_HOME`, `AGENT_UID`, `AGENT_GID` are inherited from
`agent-shell-base` (defaults: `agent`, `/home/agent`, `1000`, `1000`).

## Telegram alerting

Failures fire to `@agent_zero_cc_bot` via `FRANK_C2_TELEGRAM_BOT_TOKEN` +
`FRANK_C2_TELEGRAM_CHAT_ID` env vars (mounted from the same Infisical-backed
Secret used by Grafana and ArgoCD). If either env is empty the notifier
exits silently — the alerting path is fail-open.

## Plan / spec

- Spec: `docs/superpowers/specs/2026-05-02--orch--ruflo-pod-design.md` (`derio-net/frank`)
- Plan: `docs/superpowers/plans/2026-05-02--orch--ruflo-pod.md` (`derio-net/frank`)
