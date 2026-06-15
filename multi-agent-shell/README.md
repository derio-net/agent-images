# multi-agent-shell

SSH-able shell image carrying four agent-CLI harnesses
(`claude`, `codex`, `agy`, `opencode`). The load-bearing reference
implementation of the
[multi-harness shell standard](../docs/standards/multi-harness-shells.md):
per-harness state under `$HOME` on the per-pod PV, no API tokens in the
image, an inventory installer that knows the three new schema keys
(`harnesses`, `mcp-servers`, `skills`), and an auth-status MOTD printed on
SSH login.

Intended consumers:

- The n8n sidecar use case — workflow nodes `exec` into this shell to invoke
  `claude -p`, `codex`, `agy`, or `opencode` against a shared pod
  filesystem with PV-resident OAuth credentials.
- `infra-shell` (Phase 3 of the agent-shells-batch plan) builds **FROM**
  this image and adds cluster-admin tooling.

## Harness manifest

Per the standard's "Harness manifest" section, every harness baked into this
image is declared below. The bootstrap install only puts the CLI on PATH;
the operator runs the auth command once on first SSH and the OAuth credential
lands on the PV. For the npm harnesses, updates flow via `<h> update` (CLI
self-update) or the inventory `harnesses:` key on each reconcile; `agy` is the
exception — it has no self-update and is refreshed by image rebuild (see note).

| Harness | Bootstrap | Auth command | Credential file (on PV) | Update command |
|---|---|---|---|---|
| `claude` | `npm i -g @anthropic-ai/claude-code` (inherited from `agent-base`) | `claude login` | `~/.claude/credentials.json` | `claude update` |
| `codex` | `npm i -g @openai/codex@${CODEX_VERSION}` | `codex login` | `~/.config/codex/auth.json` | `codex update` (or inventory `harnesses: codex: <ver>`) |
| `agy` (antigravity) | `curl -fsSL …/install.sh \| bash -s -- --dir /usr/local/bin` (replaces gemini CLI) | `agy` (first run prompts the OAuth flow) | `~/.gemini/antigravity-cli/antigravity-oauth-token` | **image rebuild** (no self-update; not inventory-managed) |
| `opencode` | `npm i -g opencode-ai@${OPENCODE_VERSION}` | `opencode auth login` | `~/.local/share/opencode/auth.json` | inventory `harnesses: opencode: <ver>` |

Notes:

- **Credential paths are the MOTD detector's contract** (see
  `rootfs/etc/profile.d/50-multi-agent-shell-motd.sh`). When upstream changes
  one, update the MOTD checks and this table together.
- **`opencode` credential path is a best-effort default** until first
  operator login confirms upstream's chosen location; if it differs, fix
  here and in the MOTD detector — both must agree.
- **`agy` (antigravity) is a bootstrap-only harness.** It is
  binary-distributed (no npm), has no `agy update` subcommand and no
  version-pin mechanism, so it is updated by **image rebuild** and is
  intentionally **absent from the inventory `harnesses:` key**. Its OAuth
  token lands at `~/.gemini/antigravity-cli/antigravity-oauth-token`
  (confirmed 2026-06-15 by completing a real login in this image — a plain
  file, not an OS keyring, so the MOTD presence check works on a headless
  pod). Auth is interactive OAuth on first run of `agy` (no `agy login`, no
  API key).
- **No `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / etc. in the image or in
  Frank's `env:` block for this image.** The subscription-OAuth flows replace
  API-key auth per the standard.

## Inventory schema

The inventory installer is the same shape as `paperclip-shell`/`ruflo-shell`
(`mise`, `npm-global`, `pipx`, `cargo`, `removed`) **plus** the three new
keys mandated by the multi-harness standard. All three are optional;
fail-open semantics match the existing keys (a broken install logs + fires a
Telegram alert and lets sshd come up anyway).

```yaml
# Existing keys (unchanged) ---------------------------------------------------
mise:
  - python@3.12
  - node@22
npm-global:
  - "@anthropic-ai/claude-code"
pipx:
  - ruff
cargo:
  - ripgrep

# New keys (multi-harness standard) ------------------------------------------

# Per-harness CLI pins. "latest" floats; a specific version pins.
# Reconcile invokes each harness's update command from the manifest above.
harnesses:
  claude: latest
  codex: latest
  opencode: 1.15.13
  # NB: agy (antigravity) is NOT listed here — it has no `agy update`
  # subcommand and is refreshed by image rebuild, not inventory reconcile.

# Per-harness MCP servers. Each entry is merged into the harness's
# mcp.json by .name (idempotent — re-running reconcile produces no
# duplicates).
mcp-servers:
  claude:
    - name: context7
      command: npx
      args: ["-y", "@upstash/context7-mcp"]
  codex: []
  opencode: []

# Per-harness skills/plugins. Reconcile clones (or fast-forwards to ref)
# each git source into the harness's skills/ directory under $HOME.
skills:
  claude:
    - name: superpowers
      source: git+https://github.com/obra/superpowers
      ref: main
  codex: []
  opencode: []
```

Source of truth: `/etc/multi-agent-shell/inventory.yaml` (mounted ConfigMap
on Frank). Removed semantics mirror the existing block and are implemented
for all three new keys:

```yaml
removed:
  harnesses:        # deletes $HOME/.local/bin/<h> if a PV shim is present
    - opencode
  mcp-servers:      # deletes the named server from $HOME/.<harness>/mcp.json
    claude:
      - context7
  skills:           # deletes $HOME/.<harness>/skills/<name>
    claude:
      - superpowers
```

## First-boot operator runbook

1. SSH to the pod (`ssh -p 2222 agent@<pod-ip>`).
2. The MOTD prints the auth-status table — all four harnesses show
   `✗ not logged in`.
3. Run each `<h> login` once. OAuth opens in your local browser; the
   credential lands on the PV at the path in the manifest table above.
4. Re-login (`exit && ssh ...`). MOTD now shows `✓ <h>` for the harnesses
   you logged in to.
5. (Optional.) Edit `inventory.yaml` on Frank with the desired `harnesses:`,
   `mcp-servers:`, and `skills:` content; the next pod restart (or running
   `multi-agent-shell-reconcile` interactively) applies them.

From this point, restarts and image updates are zero-touch — the PV
preserves auth, skills, MCP configs, and self-updated CLI binaries.

## Layered install model

Same three-layer model as `paperclip-shell`:

| Layer | Source | Where it lands | When |
|---|---|---|---|
| 1 — Image baseline | this Dockerfile | image rootfs (immutable) | image build |
| 2 — Inventory | mounted ConfigMap `inventory.yaml` | per-user PV under `$HOME` | every container boot via `cont-init.d/40-shell-inventory` |
| 3 — Interactive | operator typing `mise install …`, `<h> install …`, etc. | per-user PV under `$HOME` | on demand inside the SSH session |

## Operator commands

```bash
# Re-run the inventory installer without restarting the pod
multi-agent-shell-reconcile

# Read the last reconcile log
cat /var/log/cont-init.d/40-shell-inventory.log

# Read the MOTD that prints on every login
cat /var/lib/multi-agent-shell/last-reconcile.motd
```

## Build args

| Arg | Default | Notes |
|---|---|---|
| `BASE_SHA` | `latest` | The `agent-shell-base` tag/SHA to inherit from. CI passes the SHA of the same workflow run. |
| `CODEX_VERSION` | `0.136.0` | `@openai/codex` npm pin. |
| `OPENCODE_VERSION` | `1.15.13` | `opencode-ai` npm pin. |

`agy` (antigravity) has no build-arg pin — it is installed at the latest
version by the vendor script (the installer exposes no version flag).

`AGENT_USER`, `AGENT_HOME`, `AGENT_UID`, `AGENT_GID` are inherited from
`agent-shell-base` (defaults: `agent`, `/home/agent`, `1000`, `1000`).

## Smoke test

CI job: `smoke-test-multi-agent-shell` in
[`.github/workflows/build.yaml`](../.github/workflows/build.yaml). Asserts
the standard's smoke contract: sshd up under K8s-equivalent
securityContext, every harness reports `--version` cleanly as UID 1000, and
`multi-agent-shell-reconcile` produces a clean exit and a non-empty MOTD
against an empty inventory.

Local bats coverage:

```bash
cd multi-agent-shell
bats tests/test_motd.bats              # auth-status MOTD detector
bats tests/test_install_inventory.bats # harnesses/mcp-servers/skills handlers
```

## Telegram alerting

Failures fire to `@agent_zero_cc_bot` via `FRANK_C2_TELEGRAM_BOT_TOKEN` +
`FRANK_C2_TELEGRAM_CHAT_ID` env vars (same Infisical-backed Secret used by
the other shells). Fail-silent if either env is empty.

## agent-session — persistent-agent interface

`agent-session` (baked at
`/usr/local/lib/multi-agent-shell/agent-session`, symlinked onto `PATH`)
drives a **running** interactive agent session over HTTP — never `claude -p`.
It is the reusable, versioned contract every consumer shares (n8n, the
alert-agent, …); stdlib-only Python, no extra deps.

How it drives the session: submit the message via tmux **bracketed paste**
(multi-line safe), then read the reply from a **per-turn nonce file** the
agent is asked to write (the file appearing + parsing IS the completion
signal — robust to TUI soft-wrapping). A locked, atomic per-session turn
counter is the continuity evidence.

### Serving (opt-in)

A baked **s6 longrun** (`/etc/services.d/agent-session-server`) serves the
endpoint **only when `AGENT_SESSION_SERVE=1`** (default off — a plain
interactive shell is unaffected; consumers opt in). s6 supervises restarts;
there is no postStart hook or restart loop to wire up. `agent-session send
'<json>'` runs the same core as a CLI for debug/manual use.

### API

```
POST /session/send   {session_id, agent, message, timeout_s?}
                  -> {session_id, agent, status, turn, payload}
GET  /healthz        -> 200 {"status":"ok"}
```

Bound on `127.0.0.1:${AGENT_SESSION_PORT:-8765}` (pod-local; same netns as the
consumer — never the wildcard address). `status` is `ok` or `timeout` (the
per-turn file never appeared); on timeout `payload` is `null`, so a consumer
can fall back to a deterministic render.

### Environment

| Var | Default | Purpose |
|-----|---------|---------|
| `AGENT_SESSION_SERVE` | `0` | `1` starts the baked serve longrun |
| `AGENT_SESSION_PORT` | `8765` | loopback port the HTTP server binds |
| `AGENT_SESSION_TURN_DIR` | `~/.agent-session` | per-session turn counters |
| `AGENT_SESSION_OUT_DIR` | `~/.agent-session/out` | per-turn output files |
| `AGENT_SESSION_POLL_S` | `2` | output-file poll interval (s) |
| `AGENT_SESSION_SETTLE_S` | `0.5` | paste→Enter settle delay (s) |

Each `AGENT_SESSION_*` var falls back to the legacy `STOA_*` name
(`STOA_TURN_DIR`, `STOA_OUT_DIR`, `STOA_SESSION_PORT`, `STOA_POLL_S`,
`STOA_SETTLE_S`) when unset — a **deprecated alias kept for one migration
cycle** so a consumer mid-migration never breaks.

### Per-agent launch profiles

`ensure_session` auto-creates the session by launching the configured `agent`
(the `agent` field in the request), defaulting to `claude`:

| `agent` | Launch command | Status |
|---------|----------------|--------|
| `claude` (default) | `claude --permission-mode auto` | wired + verified |
| `codex` | `codex --full-auto` | config-selectable — **auto-approve invocation not yet verified live (follow-up)** |
| `antigravity` | `agy --yolo` | config-selectable — **auto-approve invocation not yet verified live (follow-up)** |

An unrecognized `agent` falls back to the verified `claude` profile. The auto-
approve flag lets the session write its per-turn output file without a prompt
(short of a full permissions bypass). Correcting a `codex`/`antigravity` flag
is a one-line edit to the `LAUNCH_PROFILES` table in the driver.

## Plan / spec

- Standard: [`docs/standards/multi-harness-shells.md`](../docs/standards/multi-harness-shells.md)
- Spec: [`docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md`](../docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md)
- Plan: [`docs/superpowers/plans/2026-06-01-agent-shells-batch/`](../docs/superpowers/plans/2026-06-01-agent-shells-batch/)
