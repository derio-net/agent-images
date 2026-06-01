# Agent Shells Batch: hermes-agent-shell, multi-agent-shell, infra-shell

**Date:** 2026-05-12
**Status:** Draft
**Standard:** [docs/standards/multi-harness-shells.md](../../standards/multi-harness-shells.md)

## Problem

`agent-images` has SSH-able shells for one-harness use cases (`ruflo-shell`
and `paperclip-shell` host `claude`; `secure-agent-kali` adds pentest +
cluster tooling on top). It has no shells for the following three needs:

1. A **hermes agent shell** — a dedicated pod-bound shell that runs the
   `hermes` agent against the in-cluster LiteLLM gateway.
2. A **multi-harness sidecar shell** for n8n (and future workflow engines)
   so that workflow nodes can invoke `claude -p`, `codex`, `gemini`, or
   `opencode` over a shared pod filesystem, using each agent's
   subscription/OAuth auth rather than pasted API tokens.
3. An **infra-shell** that carries the same multi-harness payload plus
   cluster-admin tooling, intended to eventually replace
   `secure-agent-kali`.

Cookie-cuttering three shells without a shared standard would re-introduce
the divergence the existing repo has tried to avoid. The companion
[multi-harness shells standard](../../standards/multi-harness-shells.md)
governs the cross-cutting concerns; this spec covers the three concrete
images.

## Solution

Add one new intermediate base image plus three leaves:

```
agent-base
└── agent-shell-base
    ├── hermes-agent-shell         (new — hermes only, LiteLLM-wired)
    └── multi-agent-shell          (new — claude+codex+gemini+opencode)
        └── infra-shell            (new — multi-agent-shell + cluster admin)
```

`multi-agent-shell` is the load-bearing addition: it bakes the four
subscription-auth harnesses, implements the multi-harness standard's
manifest + MOTD + inventory-extension behaviour, and is consumed both
directly (n8n sidecar) and transitively (infra-shell).

`hermes-agent-shell` is a separate leaf off `agent-shell-base`, not off
`multi-agent-shell`, because it is the one image in the batch that retains
LiteLLM/`OPENAI_BASE_URL` wiring (hermes has no subscription auth flow
today). Mixing it with the subscription-auth shells would muddle the
standard's auth contract.

## Per-image designs

### `multi-agent-shell`

`FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}`.

**Harnesses baked:** `claude`, `codex`, `gemini`, `opencode`. Each
installed via `npm install -g` (image rootfs) as a bootstrap shim. Per the
standard, the CLI is expected to self-update into `$HOME/.local/bin/` on
first run. For any of the four that lacks a self-update mechanism, the
image-level spec for that harness (TBD during implementation) prescribes
inventory-driven install into `$HOME/.npm-global` instead.

Note: `claude` is already installed by `agent-base/Dockerfile:40`; this
image inherits it. The Dockerfile only needs to add `codex`, `gemini`,
`opencode`.

**Harness manifest entries** (per the standard):

| Harness | Bootstrap | Auth command | Credential file | Update cmd |
|---|---|---|---|---|
| claude | `npm i -g @anthropic-ai/claude-code` (inherited) | `claude login` | `~/.claude/credentials.json` | `claude update` |
| codex | `npm i -g @openai/codex` (TBD pkg name) | `codex login` (TBD) | `~/.config/codex/auth.json` (TBD) | TBD |
| gemini | `npm i -g @google/gemini-cli` (TBD pkg name) | `gemini login` (TBD) | `~/.config/gemini/auth.json` (TBD) | TBD |
| opencode | `npm i -g <pkg>` (TBD pkg name) | `opencode auth login` (TBD) | TBD | TBD |

Every TBD in the table above is intentional — those values are upstream
facts to be confirmed at implementation time, not architectural choices.
The spec is correct as long as the standard's properties are satisfied;
mis-pinning the package name doesn't change the design.

**Inventory installer:**

Mirrors `paperclip-shell`/`ruflo-shell` shape (`/etc/cont-init.d/40-shell-inventory`,
`install-base-runtimes.sh`, `install-inventory.sh`, `notify-telegram.sh`,
MOTD drop-in) **plus** the three new schema keys from the standard:
`harnesses`, `mcp-servers`, `skills`.

Per-image namespace: `/etc/multi-agent-shell/`, `/var/lib/multi-agent-shell/`,
`/usr/local/lib/multi-agent-shell/`, `/usr/local/bin/multi-agent-shell-reconcile`.
ConfigMap mount path on Frank: `/etc/multi-agent-shell/inventory.yaml`.

**MOTD:**

The auth-status table from the standard (presence check on each
credential file) replaces the simpler "last reconcile" MOTD that
paperclip-shell uses. The reconcile summary is still printed; the auth
table is appended.

**Runtime env:**

Image carries no `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other API
token. Subscription/OAuth credentials live in `$HOME` on the PV. The
Frank-side manifest's `env:` block is intentionally minimal for this
image.

**n8n consumer model:**

n8n invokes harnesses by `exec`ing into this sidecar (either via
`shareProcessNamespace: true` in the pod spec or via in-cluster `kubectl
exec`, both Frank-side concerns). The image's contribution is:

- All four CLIs on PATH at UID 1000.
- A workspace volume mount point at `/workspace` (convention; the
  Frank manifest binds the actual PVC).
- sshd on 2222 for operator login (needed for first-boot `<agent> login`
  flows).

### `hermes-agent-shell`

`FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}`.

**Harness baked:** `hermes` only. No claude/codex/gemini/opencode in this
image — keeps the identity clean and the image small.

**Harness manifest entry:**

| Harness | Bootstrap | Auth | Credential | Update |
|---|---|---|---|---|
| hermes | TBD (npm/pip/binary) at pinned `HERMES_GIT_REF` | n/a — BYOK via env | n/a | inventory reconcile / image rebuild |

Hermes is the documented exception to the standard's "no API tokens"
contract: it has no subscription/OAuth flow today, so its inference auth
is `OPENAI_BASE_URL` + `OPENAI_API_KEY` set by the Frank manifest, sourced
via ESO from Infisical. The standard's auth-status MOTD shows hermes as
`(BYOK — no login flow)` rather than `✓` or `✗`.

**Runtime env (Frank-supplied):**

| Env | Purpose | Source |
|---|---|---|
| `OPENAI_BASE_URL` | In-cluster LiteLLM | `http://litellm.litellm-system:4000/v1` |
| `OPENAI_API_KEY` | LiteLLM key | ESO → Infisical |

**Inventory installer:** same shape as paperclip-shell. Per-image
namespace: `/etc/hermes-agent-shell/`, etc. The three new inventory keys
from the standard are supported but expected to be sparse — `harnesses:
hermes: latest` is the typical content.

**Items deferred to implementation phase:**

- Upstream hermes repo URL (encoded in Dockerfile, not a build arg).
- Initial `HERMES_GIT_REF` SHA.
- Install method (npm/pip/binary).
- Whether hermes has its own service port or runs purely interactively.

### `infra-shell`

`FROM ghcr.io/derio-net/multi-agent-shell:${BASE_SHA}`.

**Inherits:** the four subscription-auth harnesses, the multi-harness
standard's full implementation, the inventory pattern, the auth-status
MOTD.

**Adds:** cluster-admin tooling — `kubectl`, `talosctl`, `omnictl` (the
same set `secure-agent-kali` currently carries via its own Dockerfile).
Per-image namespace: `/etc/infra-shell/`, `/var/lib/infra-shell/`, etc.

**Does not add (intentional default):** the Kali pentest stack
(`nmap`/`metasploit`/`burpsuite`/etc.) that `secure-agent-kali` carries.
The default scope is **cluster ops + multi-agent CLIs**, not pentest. If
pentest packages are needed on a given pod, they go through the inventory
layer (`apt`-via-inventory is a small extension to the existing
inventory installer, tracked as a follow-up in the standard's open
questions).

If on review the user prefers infra-shell to fully replace
secure-agent-kali including its pentest payload, the change is mechanical
— bake the same apt packages this Dockerfile, and rename the matrix entry.
Calling this out so the choice is explicit, not a guess.

**Migration from `secure-agent-kali`:**

This batch does not delete `secure-agent-kali`. The CI matrix keeps
building it until infra-shell has proven itself on Frank in the role
secure-agent-kali plays today. Removal is a follow-up PR tracked in the
Frank repo, not here.

## CI integration (`.github/workflows/build.yaml`)

Additive edits, no rewrites:

1. **Add `build-multi-agent-shell`** as a parallel intermediate to
   `build-shell-base` (both depend on `build-base`; `build-children`
   depends on both). This mirrors how `build-shell-base` exists between
   `build-base` and `build-children` today — `multi-agent-shell` plays the
   same role for its descendants.

   ```yaml
   build-multi-agent-shell:
     needs: build-shell-base
     # … standard build-push, BASE_SHA=needs.build-shell-base.outputs.sha
   ```

2. **Add three matrix entries** under `build-children`:

   ```yaml
   - name: hermes-agent-shell
     context: hermes-agent-shell
     build_args: |
       BASE_SHA=${{ needs.build-shell-base.outputs.sha }}
   - name: multi-agent-shell
     context: multi-agent-shell
     build_args: |
       BASE_SHA=${{ needs.build-shell-base.outputs.sha }}
   - name: infra-shell
     context: infra-shell
     build_args: |
       BASE_SHA=${{ needs.build-multi-agent-shell.outputs.sha }}
   ```

   `infra-shell` depends on `multi-agent-shell`'s SHA, not `shell-base`'s.

3. **Add three smoke-test jobs** (`smoke-test-hermes-agent-shell`,
   `smoke-test-multi-agent-shell`, `smoke-test-infra-shell`) mirroring
   the existing per-image smoke tests. Each asserts, per the standard:

   - sshd up under K8s-equivalent securityContext (existing pattern).
   - Every harness in the image's manifest reports `--version` cleanly.
   - `<image>-shell-reconcile` runs against an empty inventory with clean
     exit and MOTD present.
   - For `infra-shell`: also `kubectl version --client`, `talosctl
     version --client`, `omnictl --version` (matches secure-agent-kali's
     existing smoke).

4. **Add the three new smoke jobs to `dispatch-frank.needs`** so a broken
   shell can't reach Frank.

5. **Do not yet remove `secure-agent-kali` from the matrix.** See migration
   note above.

## README updates

Top-level `README.md` Images table gains three rows. Per-image READMEs are
written per the standard's "Adopting the standard" checklist and link
back to the standard doc.

## Items deferred to implementation phase

Tracked here so the plan author has the complete list:

- Upstream package names and install commands for `codex`, `gemini`,
  `opencode`, `hermes`.
- Each harness's exact credential-file path (used by the MOTD detector).
- Each harness's self-update mechanism vs. inventory-driven update.
- The MCP servers and skills the user actually wants pre-listed in the
  default inventory (the spec only defines schema; the data is operator
  choice).
- Whether `superpowers` / `superpowers-for-vk` / `openspec` / `context7`
  ship as MCP servers, claude-code plugins/skills, or both, and the
  mapping to inventory keys (also flagged in the standard's open
  questions).

## Scope

- **In scope:** Three new image directories (Dockerfile + rootfs + README
  per the standard's checklist), one new intermediate-base CI job, three
  new matrix entries, three new smoke-test jobs, README + standard
  cross-links.
- **Out of scope:** Frank-side pod/service manifests for any of the three
  images; ESO mappings; removal of `secure-agent-kali`; the actual list of
  MCP servers and skills the operator pre-loads; cross-harness skill
  unification.

## Implementation Plans

| Plan | Repo | File | Depends on |
|------|------|------|------------|
| 2026-06-01-agent-shells-batch | `derio-net/agent-images` | `docs/superpowers/plans/2026-06-01-agent-shells-batch/` | — |
