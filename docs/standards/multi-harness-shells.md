# Multi-Harness Shell Standard

**Status:** Draft (living document)
**Applies to:** any `*-shell` image in this repo that hosts one or more agent-CLI
harnesses (`claude`, `codex`, `agy`, `opencode`, `hermes`, future harnesses).
**Does not apply to:** server images (`ruflo-server`, `vk-local`).

## Purpose

Multiple agent-CLI harnesses must be able to coexist in a single shell image
and run against any repository, regardless of whether that repo is set up for
one specific harness or none. Image rebuilds must not be required to update
harnesses, skills, MCP servers, or extensions. Operator credentials must
survive container restarts and image updates without re-running interactive
login flows.

This document is the contract that all `*-shell` images in this repo
implement. Image-level specs reference this doc rather than re-stating it.

## Scope

- **In scope:** the agent user's `$HOME` layout, harness install/update
  mechanism, auth credential storage, skill/MCP/extension persistence,
  inventory schema extension, the per-harness contract for being a
  well-behaved citizen.
- **Out of scope:** specific upstream harness versions (pinned per image),
  Frank-side pod manifests, RBAC, network policy, ingress, ESO mappings.

## Architectural premise

Everything that needs to survive a container restart or image update lives on
the per-pod **home PV** at `$AGENT_HOME` (default `/home/agent`). Everything
on the image rootfs is treated as immutable and reproducible from the
Dockerfile. The split:

| Concern | Lives in | Updated by | Survives restart? |
|---|---|---|---|
| OS packages, shell base, s6, tmux | image rootfs | image rebuild | n/a (re-created from image) |
| Harness CLI **bootstrap shim** | image rootfs (`npm i -g …`) | image rebuild | n/a |
| Harness CLI **current version** | `$HOME/.local/bin/` (self-update target) | `<agent> update` or inventory reconcile | yes |
| Harness auth credentials | `$HOME/.<agent>/` or `$HOME/.config/<agent>/` | interactive `<agent> login` once | yes |
| Skills / plugins | `$HOME/.<agent>/skills/`, `$HOME/.<agent>/plugins/` (per-harness) | inventory reconcile or operator | yes |
| MCP server configs | `$HOME/.<agent>/mcp.json` (per-harness) | inventory reconcile or operator | yes |
| MCP server binaries | usually `npx`/`uvx` transient; sometimes `$HOME/.local/bin/` | reconcile or operator | yes |
| Per-repo agent config | inside the repo (`<repo>/.claude/…`) | the repo's own commits | yes (repo on PV) |
| Per-user inventory state | `$HOME/.local/state/<image>-shell/` | reconcile | yes |

The single rule that makes the whole thing coherent: **no harness state of any
kind is stored on the image rootfs.** The rootfs is a starting template, not a
record.

## Persistence layout (`$HOME`)

```
$HOME/
├── .local/
│   ├── bin/                  # self-updated harness binaries, mise shims
│   └── state/<image>-shell/  # inventory reconcile state, last-run logs
├── .config/                  # XDG-Base-Dir per-harness configs that follow XDG
│   ├── codex/                # auth.json, settings.json (TBD per upstream)
│   └── opencode/             # (TBD per upstream)
├── .gemini/antigravity-cli/  # agy (antigravity) settings.json + antigravity-oauth-token
│                             #   (agy reuses the ~/.gemini dir; not XDG)
├── .claude/                  # claude-code; canonical layout — see below
│   ├── credentials.json
│   ├── settings.json
│   ├── plugins/
│   ├── skills/
│   ├── agents/
│   └── mcp.json
├── .hermes/                  # hermes agent state (TBD per upstream)
├── .ssh/                     # operator SSH keys (provisioned by 01-pvc-dirs)
└── repos/                    # cloned repos; per-repo configs live here
```

**`.claude/` is normative for claude-code** because that's what upstream
expects and what `agent-base` already targets. The XDG-style `~/.config/`
layout applies to harnesses whose upstreams follow XDG. Where upstream is
ambiguous, the image-level spec records the chosen path; this doc does not
override upstream.

## Harness manifest

Each `*-shell` image declares which harnesses it carries. For every
harness, the image's README lists:

1. **Bootstrap install** — the Dockerfile line that puts the CLI on PATH.
   Usually `npm i -g <pkg>`, but it may instead be a vendor binary installer
   (e.g. `agy`/antigravity installs via `curl …/install.sh | bash -s -- --dir
   /usr/local/bin`).
2. **Self-update path** — where the CLI writes updates (`$HOME/.local/bin/`
   preferred). If the upstream CLI has no self-update mechanism, install via
   the inventory layer with an npm prefix of `$HOME/.npm-global` so updates
   land on the PV.
3. **Auth command** — the operator-run command that produces persistent
   credentials (`claude login`, `codex login`, …).
4. **Auth credential file(s)** — the path(s) on `$HOME` that prove the
   harness is logged in, used by the MOTD detector below.
5. **Update command** — the command run by `<image>-shell-reconcile` to
   refresh the CLI to the inventory-pinned version (or latest).

If an upstream CLI does not satisfy properties 2 or 3, the image-level spec
must call out the gap and propose a workaround (typically: install via
inventory into `$HOME/.npm-global`, or wrap with a daemon that holds an
issued session).

## Auth model — subscription, not API tokens

For harnesses that ship a subscription/OAuth login flow (claude, codex,
agy, …) the standard mandates that flow over any API-key env-var
mechanism. The implications:

- The image **does not** carry an `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` /
  similar env at build or runtime. No `EnvFrom` references such keys for
  these harnesses on Frank.
- First boot of a new pod is **interactive**: the operator SSHes in and runs
  each `<agent> login` once. The OAuth browser flow lands its credential in
  `$HOME` on the PV. From that point, restarts and image updates are
  zero-touch.
- For harnesses with no subscription/OAuth path (e.g., `hermes` today, which
  is BYOK to an OpenAI-compatible endpoint), the image-level spec records
  the exception and how its credentials are sourced. The Frank-side
  manifest, not the image, owns those env vars.

Cross-implication: a `*-shell` image carrying multiple subscription harnesses
is only "ready" once every harness in its manifest has been logged in. The
MOTD makes this state visible (see below).

## Auth status MOTD

Every `*-shell` image must ship an `/etc/profile.d/` drop-in that, on each
SSH login, prints a per-harness auth status table:

```
Harness auth status:
  ✓ claude     (~/.claude/credentials.json, age 4d)
  ✓ codex      (~/.config/codex/auth.json, age 4d)
  ✗ agy        not logged in — run: agy
  ✗ opencode   not logged in — run: opencode auth login
```

The detector reads only the credential file paths declared in the harness
manifest. It is a presence check, not a freshness or validity check — the
operator owns rotation.

## Updates — image immutable, $HOME mutable

Updates to harness CLIs, skills, MCP servers, and extensions never require an
image rebuild. The three mechanisms:

1. **CLI self-update** — preferred. `claude` does this natively; the standard
   requires that every other harness either self-updates or be installed via
   inventory into a PV-backed npm prefix.
2. **Inventory reconcile** — the existing `<image>-shell-reconcile` script
   (e.g., `paperclip-shell-reconcile`) runs the configmap-mounted
   `inventory.yaml` against the PV. The schema is extended below to cover
   harnesses, MCP servers, and skills.
3. **Operator-driven install** — interactive `mise install`, `npm i`,
   `claude plugin install`, etc., performed in an SSH session. Already
   supported by the existing shell pattern.

Image rebuilds are reserved for: changing the bootstrap shim itself, OS
package upgrades, base-image bumps, security patches.

## Inventory schema extension

The existing `inventory.yaml` schema (paperclip-shell, ruflo-shell) is
extended with three new top-level keys, all optional. Existing keys
(`mise`, `npm-global`, `pipx`, `cargo`, `removed`) keep their semantics.

```yaml
# Existing keys (unchanged) ---------------------------------------------------
mise:
  - python@3.12
  - node@20
npm-global:
  - "@anthropic-ai/claude-code"
pipx:
  - ruff
cargo:
  - ripgrep
removed:
  mise: []

# New keys --------------------------------------------------------------------

# Per-harness CLI pins. Reconcile invokes each harness's update command
# (declared in the image's harness manifest). Setting a version pins; "latest"
# floats.
harnesses:
  claude: latest
  codex: latest
  opencode: 0.4.2
  # Binary-distributed harnesses with no self-update (e.g. agy/antigravity)
  # do NOT belong here — they are refreshed by image rebuild.

# Per-harness MCP servers. Each entry is appended to that harness's mcp.json
# during reconcile, idempotently (existing entries with the same name are
# replaced, not duplicated).
mcp-servers:
  claude:
    - name: context7
      command: npx
      args: ["-y", "@upstash/context7-mcp"]
    - name: superpowers
      command: npx
      args: ["-y", "superpowers-mcp"]
  codex:
    - name: context7
      command: npx
      args: ["-y", "@upstash/context7-mcp"]
  opencode: []

# Per-harness skills/plugins. Reconcile clones (or pulls) git refs into the
# harness's skills/plugins dir, or invokes the harness's own plugin command.
skills:
  claude:
    - name: superpowers
      source: git+https://github.com/<org>/superpowers
      ref: main
    - name: super-fr
      source: git+https://github.com/derio-net/super-fr
      ref: main
  codex: []
  opencode: []
```

Removal semantics mirror the existing `removed:` block — e.g.,
`removed.harnesses`, `removed.mcp-servers.claude`, `removed.skills.claude`.

Reconcile is **fail-open** for every new key, same as the existing keys: a
broken install logs the failure, fires the Telegram notifier, and lets sshd
come up anyway. Auth failures are not "installs" — they show up in the MOTD
table as `✗ not logged in`, not as installer errors.

## Skill / MCP / extension contract

Each harness has its own loader for skills/plugins/MCP. The standard does
**not** try to unify them — that's a per-harness UX concern, not an image
concern. What the standard does require:

1. **Everything per-harness lives under `$HOME`.** A user-scoped install for
   harness X must not write outside that harness's PV-backed config dir.
2. **Per-repo overrides win.** A repo with `<repo>/.claude/` overrides
   `$HOME/.claude/` for that working directory — that's claude-code's own
   behaviour, restated here so spec authors don't fight it.
3. **Missing per-repo config is non-fatal.** A repo set up only for claude
   (no `.codex/`, no agy config) must remain usable by codex and agy,
   which fall back to their `$HOME` defaults.
4. **No cross-harness pollution.** The standard does not introduce shared
   files like `~/.agent-skills/` that multiple harnesses must read.
   Operators who want symlink-based sharing can do so manually; the image
   does not mandate it.

## Smoke testing

CI smoke tests for any `*-shell` image must, at minimum:

1. Boot under K8s-equivalent securityContext (`runAsUser: 1000`,
   `cap-drop=ALL`, `no-new-privileges`) — existing pattern.
2. Wait for sshd to come up via `/command/s6-svstat /run/service/sshd`.
3. For every harness in the image's manifest, assert `<harness> --version`
   runs as UID 1000.
4. Run `<image>-shell-reconcile` against an empty inventory and assert
   clean exit + MOTD drop-in present.

CI **does not** assert auth status. Credentials are not available in CI;
auth is a runtime concern proven the first time the operator SSHes in.

## Adopting the standard in a new image

Minimum requirements for a new `*-shell` image to claim compliance:

- [ ] `FROM agent-shell-base` (directly or transitively).
- [ ] No harness state on image rootfs — auth/skills/MCP all land in `$HOME`.
- [ ] Each harness's bootstrap install satisfies the manifest properties
      above (or the spec records the gap).
- [ ] Inventory installer recognises the three new schema keys.
- [ ] MOTD prints the auth-status table on SSH login.
- [ ] CI smoke test asserts presence of every harness CLI.
- [ ] README links to this doc and lists each harness's manifest entry.

## Open questions tracked on this doc

- Self-update behaviour of `codex`, `opencode` — to be confirmed per
  upstream. If any lacks a self-update mechanism, this doc gains a
  per-harness workaround section. (`agy`/antigravity is already known to have
  **no** self-update and no version pin → refreshed by image rebuild, and is
  intentionally excluded from the inventory `harnesses:` key.)
- Whether `superpowers` (and similar) ship MCP servers, claude-code
  plugins, or both, and how that distinction maps to the
  `mcp-servers` vs `skills` inventory keys.
- Process namespace sharing for the n8n sidecar use case — relevant to
  how n8n invokes `claude -p` over the shared pod. Image-side concern is
  zero; flagged here so the Frank-side manifest spec can address it.
