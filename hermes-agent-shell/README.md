# hermes-agent-shell

SSH-able shell image carrying the [hermes agent](https://github.com/NousResearch/hermes-agent)
(Nous Research) wired to the in-cluster LiteLLM gateway. Implements the
[multi-harness shell standard](../docs/standards/multi-harness-shells.md)
as a single-harness leaf — per-harness state under `$HOME` on the per-pod
PV, sparse inventory installer, auth-status MOTD on SSH login.

`hermes-agent-shell` is the documented exception to the standard's "no API
tokens" auth contract: hermes has no subscription/OAuth login flow today,
so its inference auth is **BYOK** via `OPENAI_BASE_URL` + `OPENAI_API_KEY`
set by the Frank pod manifest and sourced via ESO from Infisical. The MOTD
reflects this with a `~ hermes (BYOK — no login flow)` row rather than the
✓/✗ pattern the other shells use.

## Harness manifest

Per the standard's "Harness manifest" section, every harness baked into
this image is declared below. hermes is single-harness; the inventory's
`harnesses:` key is typically just `hermes: latest` (or a pinned PyPI
version) and the other inventory keys stay sparse.

| Harness | Bootstrap | Auth command | Credential file (on PV) | Update command |
|---|---|---|---|---|
| `hermes` | `uv pip install hermes-agent==${HERMES_VERSION}` into a **relocatable seed** venv at `/opt/hermes-agent`, seeded onto the PVC at `/home/agent/.local/opt/hermes-agent` on first boot (see below); `hermes` entry point symlinked onto PATH | n/a — BYOK via env (`OPENAI_BASE_URL`, `OPENAI_API_KEY`) | n/a (no local credential — operator state lives at `~/.hermes/`) | inventory `harnesses: hermes: <ver>` (runs `hermes update` in the PVC venv), or image rebuild |

Notes:

- **No login flow.** The standard's MOTD detector ✓/✗ pattern does not
  apply; the `50-hermes-agent-shell-motd.sh` drop-in prints a constant
  BYOK row and a one-line hint when `OPENAI_BASE_URL` is unset.
- **PVC-resident venv (frank#496).** The image bakes a *relocatable* seed
  venv at `/opt/hermes-agent` (`uv venv --relocatable`). On first boot
  `cont-init.d/35-hermes-venv-seed` `cp -a`'s it onto the `/home/agent` PVC
  at `/home/agent/.local/opt/hermes-agent` — the **live** venv, uid-1000-owned
  and writable. So the in-pod operator can patch/maintain Hermes in place
  (`hermes update`, site-packages edits) and the changes **persist across pod
  restarts**. The seed is version-stamped (`/opt/hermes-agent/.seed-version`);
  the hook re-seeds when an image/Hermes bump changes the stamp, and is a
  no-op (preserving in-pod patches) when it matches. The launcher
  `/usr/local/bin/hermes` points at the PVC venv. The venv cannot be baked at
  the PVC path directly — the PVC mount shadows anything under `/home/agent`.
- **Baked auto-continue patch (frank#496).** `patches/hermes-autocontinue-chat-completions.patch`
  widens Hermes' "announce-only turn" countermeasure gate from
  `codex_responses` to also fire on `chat_completions` (the LiteLLM path
  Frank uses), permanently fixing the qwen36-a3b "announce then idle" stall.
  Applied at build with `git apply` (zero fuzz → the build fails if the hunk
  drifts on a `HERMES_VERSION` bump; refresh the patch then).
- **`~/.hermes/` on the PV** is hermes' own data dir (per its installer):
  config, sessions, skills, memories. It is per-operator state, never
  baked into the image.
- **Upstream pin.** `HERMES_VERSION=0.15.2` corresponds to upstream tag
  `v2026.5.29.2` (commit `77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5`,
  2026-05-29). Floats forward via inventory `harnesses:` once an operator
  overrides it on first reconcile, or via a Dockerfile bump.

## BYOK env contract (Frank-supplied)

| Env | Purpose | Source |
|---|---|---|
| `OPENAI_BASE_URL` | In-cluster LiteLLM endpoint | `http://litellm.litellm-system:4000/v1` (Frank ConfigMap / pod env) |
| `OPENAI_API_KEY` | LiteLLM API key | ESO → Infisical |

The image **does not** carry either env at build time. The MOTD surfaces
a hint when `OPENAI_BASE_URL` is unset; missing keys do not block sshd —
they just mean `hermes` cannot reach LiteLLM until the operator (or the
pod manifest) sets them.

## Inventory schema

Same shape as `multi-agent-shell`'s installer (`mise`, `npm-global`,
`pipx`, `cargo`, `removed`, **plus** the multi-harness standard's three
new keys `harnesses`, `mcp-servers`, `skills`). All optional; fail-open
semantics match the existing keys (a broken install logs + fires a
Telegram alert and lets sshd come up anyway).

A representative sparse inventory:

```yaml
# Pin hermes to a specific PyPI version; "latest" floats.
harnesses:
  hermes: latest

# Hermes loads MCP servers from $HOME/.hermes/mcp.json (per upstream).
mcp-servers:
  hermes: []

# Hermes loads skills from $HOME/.hermes/skills/<name>/.
skills:
  hermes: []
```

Source of truth: `/etc/hermes-agent-shell/inventory.yaml` (mounted
ConfigMap on Frank). Removed semantics mirror multi-agent-shell.

## First-boot operator runbook

1. Frank's pod manifest provides `OPENAI_BASE_URL` and `OPENAI_API_KEY`
   (ESO-sourced from Infisical). Without them, hermes cannot reach
   LiteLLM.
2. SSH to the pod (`ssh -p 2222 agent@<pod-ip>`).
3. The MOTD prints the BYOK row. If `OPENAI_BASE_URL` is missing, the
   MOTD surfaces a hint.
4. Run `hermes` interactively (or `hermes chat`, `hermes setup`) — first
   run writes `~/.hermes/` on the PV and persists across restarts and
   image updates.
5. (Optional.) Edit `inventory.yaml` on Frank to pin a `hermes` version,
   declare per-harness MCP servers, or clone skills. The next pod restart
   (or `hermes-agent-shell-reconcile` interactively) applies them.

## Layered install model

Same three-layer model as `multi-agent-shell` and `paperclip-shell`:

| Layer | Source | Where it lands | When |
|---|---|---|---|
| 1 — Image baseline | this Dockerfile | image rootfs: relocatable **seed** venv `/opt/hermes-agent` + launcher `/usr/local/bin/hermes` | image build |
| 1.5 — Venv seed | relocatable seed at `/opt/hermes-agent` | **live** venv on PV `/home/agent/.local/opt/hermes-agent` (uid-1000 writable) | first boot / image bump via `cont-init.d/35-hermes-venv-seed` |
| 2 — Inventory | mounted ConfigMap `inventory.yaml` | per-user PV under `$HOME` | every container boot via `cont-init.d/40-shell-inventory` |
| 3 — Interactive | operator typing `hermes …`, `mise install …`, etc. | per-user PV under `$HOME` | on demand inside the SSH session |

## Operator commands

```bash
# Re-run the inventory installer without restarting the pod
hermes-agent-shell-reconcile

# Read the last reconcile log
cat /var/log/cont-init.d/40-shell-inventory.log

# Read the MOTD that prints on every login
cat /var/lib/hermes-agent-shell/last-reconcile.motd
```

## Build args

| Arg | Default | Notes |
|---|---|---|
| `BASE_SHA` | `latest` | The `agent-shell-base` tag/SHA to inherit from. CI passes the SHA of the same workflow run. |
| `HERMES_VERSION` | `0.15.2` | `hermes-agent` PyPI pin. Bump to bake a newer upstream tag. |

`AGENT_USER`, `AGENT_HOME`, `AGENT_UID`, `AGENT_GID` are inherited from
`agent-shell-base` (defaults: `agent`, `/home/agent`, `1000`, `1000`).

## Smoke test

CI job: `smoke-test-hermes-agent-shell` in
[`.github/workflows/build.yaml`](../.github/workflows/build.yaml). Asserts
the standard's smoke contract: sshd up under K8s-equivalent
securityContext, `hermes --version` runs cleanly as UID 1000, and
`hermes-agent-shell-reconcile` produces a clean exit and a non-empty MOTD
against an empty inventory. The BYOK MOTD drop-in is asserted present and
runnable.

Local bats coverage:

```bash
cd hermes-agent-shell
bats tests/test_motd.bats              # BYOK MOTD + OPENAI_BASE_URL hint
bats tests/test_install_inventory.bats # harnesses/mcp-servers/skills handlers
```

## Telegram alerting

Failures fire to `@agent_zero_cc_bot` via `FRANK_C2_TELEGRAM_BOT_TOKEN` +
`FRANK_C2_TELEGRAM_CHAT_ID` env vars (same Infisical-backed Secret used by
the other shells). Fail-silent if either env is empty.

## Plan / spec

- Standard: [`docs/standards/multi-harness-shells.md`](../docs/standards/multi-harness-shells.md)
- Spec: [`docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md`](../docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md)
- Plan: [`docs/superpowers/plans/2026-06-01-agent-shells-batch/`](../docs/superpowers/plans/2026-06-01-agent-shells-batch/)
