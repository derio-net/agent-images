# Design: Replace gemini CLI with antigravity CLI (`agy`) in multi-agent-shell

**Issue:** [#119](https://github.com/derio-net/agent-images/issues/119)
**Date:** 2026-06-15
**Branch:** `feat/antigravity-cli-swap`
**Status:** Draft → implementation

## Context & goal

Google's **gemini CLI is being replaced by the antigravity CLI** (`agy`) and the
gemini CLI deprecates upstream ~**2026-06-18** (≈3 days out). The
`multi-agent-shell` image bakes `@google/gemini-cli` as one of its four
harnesses (`claude`, `codex`, `gemini`, `opencode`) and the *multi-harness shell
standard* lists `gemini` as a canonical harness. We must swap `gemini` → the
antigravity CLI across the image, its manifest/docs/tests, the MOTD auth
detector, and the standard — before gemini CLI disappears upstream.

`infra-shell` builds **FROM** `multi-agent-shell`, so it inherits the harness
binaries and carries its own MOTD copy + CI smoke assertions that also reference
gemini.

## The antigravity CLI — researched facts (2026-06-15)

| Property | gemini CLI (current) | antigravity CLI (`agy`) |
|---|---|---|
| Distribution | npm: `@google/gemini-cli` | **shell installer**: `curl -fsSL https://antigravity.google/cli/install.sh \| bash` (not npm) |
| Binary name | `gemini` | **`agy`** (installer drops it at `~/.local/bin/agy`) |
| Auth | `gemini` first-run → OAuth | `agy` first-run → Google OAuth; **headless prints a URL + one-time code** |
| API-key option | `GEMINI_API_KEY` | `ANTIGRAVITY_API_KEY` — **must NOT be used** (see constraints) |
| Config dir | `~/.config/gemini/` | `~/.gemini/antigravity-cli/settings.json` |
| Credential file | `~/.config/gemini/auth.json` | **`~/.gemini/antigravity-cli/credentials.enc`** (encrypted; key derived from OS keychain / Secret Service on Linux) — *best-effort, see risk R1* |
| Self-update | `gemini update` / inventory pin | **none** — no `agy update` subcommand; updates by re-running the install script (i.e. image rebuild). `agy changelog` only reports versions. |
| Version pin | `@google/gemini-cli@<ver>` | **no documented pin mechanism** in the install script — installs latest |
| Migration | — | `agy plugin import gemini`; non-destructive, reads existing `~/.gemini/` |

Sources: antigravity.google docs/CLI guides, Google Cloud Community
"Getting Started with Antigravity CLI", gemini→agy migration guides
(inventivehq, pasqualepillitteri). Cross-checked across ≥4 sources.

## Operator constraints (locked)

1. **No API key in the environment.** These are persistent agents; do not add
   `ANTIGRAVITY_API_KEY` to the image, the Dockerfile, or any pod `env:`. This
   matches the standard's subscription-OAuth mandate (no `*_API_KEY` for these
   harnesses).
2. **Auth is interactive.** A human runs `agy` once on first SSH and completes
   the OAuth flow (headless: open the printed URL + code on a laptop). The
   credential persists on the PV. No automated/token auth.

## Q&A decisions (operator, 2026-06-15)

| # | Decision | Choice |
|---|---|---|
| 1 | Naming across docs/tests/MOTD/inventory | **Use `agy` everywhere** (the real binary). README labels it "antigravity (`agy`)". No `antigravity→agy` symlink. |
| 2 | Devcontainer profile | **Single `dev` profile, no secrets** (already scaffolded). |
| 3 | Replacement scope | **Hard-replace gemini.** Harnesses become `claude`, `codex`, `agy`, `opencode`. |
| 4 | Post-merge Test Plan | **Yes** — verify the real image on a pod (build + `agy --version` + interactive OAuth + confirm which credential file lands). |

## Design

### Harness model for `agy` — a "bootstrap-only, rebuild-updated" harness

`agy` does **not** satisfy two properties the standard expects of a harness
(self-update path; `<h> login` auth command). The standard explicitly handles
this (`docs/standards/multi-harness-shells.md` §"Harness manifest", lines
97–101: "If an upstream CLI does not satisfy properties 2 or 3, the image-level
spec must call out the gap and propose a workaround"). The workaround:

- **Bootstrap install:** run the vendor install script at build time and place
  the `agy` binary on the global PATH (`/usr/local/bin/agy`), matching where the
  npm `-g` harnesses land. The standard's "bootstrap shim" slot is satisfied by
  a binary install rather than `npm i -g`.
- **Update path:** **image rebuild** (re-run the install script). `agy` has no
  self-update and no npm pin, so it is reserved to the image-rebuild lane the
  standard already defines ("Image rebuilds are reserved for: changing the
  bootstrap shim itself…").
- **Therefore `agy` is NOT an inventory `harnesses:` pin entry.** The inventory
  handler runs `<h> update`, which `agy` lacks. `agy` is removed from the
  `harnesses:` examples and not re-added. (See Deviation D1.)
- **Auth command:** `agy` (first run), not `agy login`.
- **Credential file (MOTD contract):** `~/.gemini/antigravity-cli/credentials.enc`
  — flagged best-effort (R1), same hedge the README already applies to
  `opencode`.

### Change inventory (the full gemini footprint → agy)

| # | File | Current | New |
|---|---|---|---|
| C1 | `multi-agent-shell/Dockerfile` | `ARG GEMINI_CLI_VERSION=0.44.1`; `@google/gemini-cli@${GEMINI_CLI_VERSION}` inside the one `npm install -g` RUN | Drop the gemini ARG + npm line; add a separate `RUN` that installs `agy` via the vendor script into `/usr/local/bin/agy` and asserts `agy --version`. Update the comment block (lines 15–24) to note agy is script-installed/rebuild-updated, not npm/self-update. |
| C2 | `multi-agent-shell/README.md` | manifest row `gemini`; build-arg row; inventory examples (`harnesses`, `mcp-servers`, `skills`) with `gemini`; prose "four harnesses … gemini"; first-boot runbook | Replace the `gemini` manifest row with an `agy` row (bootstrap = install script; auth = `agy`; cred = `~/.gemini/antigravity-cli/credentials.enc` *best-effort*; update = **image rebuild — no self-update**). Drop the `GEMINI_CLI_VERSION` build-arg row. Drop `gemini` from inventory `harnesses:`/`mcp-servers:`/`skills:` examples (D1). Update prose harness lists to `claude`, `codex`, `agy`, `opencode`. |
| C3 | `multi-agent-shell/rootfs/etc/profile.d/50-multi-agent-shell-motd.sh` | `check gemini .config/gemini/auth.json` | `check agy .gemini/antigravity-cli/credentials.enc`. Extend `check` to accept an optional 3rd arg = login-hint command so the `✗` line reads "run: agy" (not "run: agy login"); default stays `<name> login` for the others. |
| C4 | `multi-agent-shell/tests/test_motd.bats` | asserts `✗ gemini`; claude-only test | Assert `✗ agy` (no-creds); add a test that an `agy` credentials file present → `✓ agy`; assert the `✗ agy` line shows "run: agy". |
| C5 | `multi-agent-shell/rootfs/usr/local/lib/multi-agent-shell/install-inventory.sh` | generic `harnesses:` handler (covers gemini) | **No code change** — the handler is generic. agy simply isn't listed in inventory examples. (If an operator adds `agy:` anyway, the existing "CLI not on PATH"/`run` failure path logs a warning — acceptable, documented in README.) |
| C6 | `docs/standards/multi-harness-shells.md` | `gemini` in: applies-to list (L5), `$HOME` layout `.config/gemini/` (L61), auth-model prose (L106), MOTD example `gemini login` (L134), inventory examples (L189/207/221), per-repo-fallback prose (L245), self-update open-question (L282) | Replace each `gemini` mention with `agy` where it's a harness reference (L5, L106, L245). Replace the `.config/gemini/` layout entry with `~/.gemini/antigravity-cli/` (L61). Update the MOTD example to `✗ agy … run: agy` (L134). Drop `gemini` from inventory examples (L189/207/221) per D1. Resolve the L282 open-question (agy = no self-update → image rebuild). Add a one-line note that a bootstrap "shim" may be a vendor binary installer (not only `npm i -g`). |
| C7 | `infra-shell/rootfs/etc/profile.d/50-infra-shell-motd.sh` | `check gemini .config/gemini/auth.json` (L31) | same edit as C3 (agy cred path + login-hint). **Note:** the `check` function body here must get the same optional-3rd-arg change as C3 (the two MOTD scripts are near-duplicates). |
| C8 | `infra-shell/README.md` | inheritance line "(`claude`, `codex`, `gemini`, …)" (L4) | `(claude, codex, agy, …)`. |
| C9 | `infra-shell/tests/` | — | **No file** — infra-shell ships no local bats tests (confirmed: only `Dockerfile`, `README.md`, `rootfs/`). infra-shell's MOTD is covered solely by the CI smoke job (C11, L844). No change. |
| C10 | `README.md` (repo root) | image table: "claude + codex + gemini + opencode" (L12) | "claude + codex + agy + opencode". |
| C11 | `.github/workflows/build.yaml` | comment "codex/gemini/opencode baked here" (L618); `for h in claude codex gemini opencode` (L619 multi-agent-shell, L844 infra-shell smoke) | Update the L618 comment and both smoke loops to `claude codex agy opencode`. |

### Explicitly out of scope / left unchanged

- `docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md` **and**
  `docs/superpowers/plans/2026-06-01-agent-shells-batch/` (01.yaml, 03.yaml,
  _prose.md) — **historical/shipped spec + plan** that record what was built
  then. We do not rewrite history; they keep their `gemini` references as an
  accurate record of the original build. (Deviation D2.)
- `agent-shell-base/Dockerfile`, `base/` — confirmed no gemini; no change.
- agy MCP-server / skills inventory wiring — agy stores MCP/skills under
  `~/.gemini/antigravity-cli/`, not the generic `~/.<harness>/` convention the
  inventory handler assumes. Wiring agy into `mcp-servers:`/`skills:` is a
  **separate follow-up**, not part of this swap. (Deviation D1.)

## Deviations from the issue's literal "rename gemini → antigravity"

- **D1 — agy is not a like-for-like inventory harness.** The issue lists
  "Inventory installer (`harnesses:` key) — rename/replace `gemini` with
  `antigravity`." Because `agy` has no `update` subcommand and no npm pin, it
  cannot be a managed `harnesses:` pin. We instead **remove** gemini from the
  inventory examples and document agy's update path as image-rebuild. The
  generic installer code is untouched.
- **D2 — historical spec untouched.** The 2026-05-12 agent-shells-batch spec is
  a record, not a living doc; left as-is.
- **D3 — binary name `agy`, label "antigravity".** Per Q&A #1 we use the real
  binary `agy` as the harness key/command everywhere; "antigravity" appears only
  as the friendly product name in prose.

## Risks

- **R1 (highest) — credential file path is unverified.** Sources disagree:
  `~/.gemini/antigravity-cli/credentials.enc` (encrypted file) vs OS-keyring-only
  storage. On a **headless container** Linux Secret Service may be absent, so the
  encrypted file may not be written, may not decrypt across restarts, or the
  token may live only in a keyring that does not persist on the PV. The MOTD
  path (C3/C7) is a best-effort guess. **The post-merge Test Plan resolves this**
  by observing what actually lands after a real `agy` login on a pod; if it
  differs, the fix is a one-line MOTD + manifest update (both already coupled).
- **R2 — build-time install script behavior.** `install.sh` auto-detects the
  environment, writes to `$HOME/.local/bin`, and edits `~/.bashrc`/`~/.profile`.
  Running it as root at build time and relocating the binary to `/usr/local/bin`
  must be verified; the CI smoke `agy --version` is the gate. Mitigation: pass a
  scratch `HOME`, relocate the binary, `rm -rf` the scratch dir, assert version.
- **R3 — no version pin → non-reproducible builds.** `agy` installs latest.
  Accepted: this matches the `claude` bootstrap (also latest); reproducibility
  for agy is traded for tracking upstream. Noted in the manifest.
- **R4 — keyring/persistence across restarts.** Tied to R1; if creds don't
  survive restart, operators re-run `agy` interactively. Captured in the Test
  Plan; no image change can fix a missing keyring, but it must be known.

## Testing strategy (pre-merge, TDD)

1. **MOTD bats (C3/C4):** drive `test_motd.bats` — RED first (assert `✗ agy`
   and the "run: agy" hint, and `✓ agy` when the credential file exists), then
   edit the MOTD script to green. Run in the devcontainer with `bats` installed
   on-demand. Mirror for infra-shell (C7/C9).
2. **shellcheck** the edited `.sh` files (install on-demand).
3. **CI build + smoke** (`.github/workflows/build.yaml`): the real gate for the
   Dockerfile change — builds the image and runs `agy --version` as UID 1000
   (C11). This catches R2. Local full-image build is out of the devcontainer's
   scope (no docker-in-docker); CI owns it.
4. **Doc consistency:** grep the tree for residual `gemini` / `@google/gemini-cli`
   / `.config/gemini` and confirm only the intentional historical spec remains.

## Test Plan (post-merge — operator-driven)

Run after the PR merges and CI publishes the image. The agent runs what it can;
the operator confirms the OAuth-gated steps.

1. **Image builds & agy present.** Confirm the CI `smoke-test-multi-agent-shell`
   (and `infra-shell`) jobs are green and that the smoke loop ran `agy --version`
   cleanly as UID 1000.
2. **Pull onto a real pod / local docker.** `docker run` (or exec into the
   deployed pod) and confirm `agy --version` and `command -v agy` →
   `/usr/local/bin/agy`.
3. **Interactive auth.** Run `agy` as the agent user; complete the headless
   OAuth (open the printed URL + one-time code on a laptop). Confirm login
   succeeds.
4. **Resolve R1 — observe the real credential path.** After login, inspect what
   landed: `ls -la ~/.gemini/antigravity-cli/` (expect `credentials.enc` +
   `settings.json`); also check for any OS-keyring artifact. **If the credential
   file path differs from `~/.gemini/antigravity-cli/credentials.enc`, update C3
   + C7 (MOTD) and the README/standard manifest row** — they are coupled and the
   fix is one line each.
5. **MOTD reflects login.** Re-SSH (or re-source the profile.d drop-in) and
   confirm the auth table shows `✓ agy (~/.gemini/antigravity-cli/…)`.
6. **Persistence across restart.** Restart the container/pod; confirm `agy`
   still authenticated (credential survived on the PV) — resolves R4. If not,
   document that agy requires re-auth per pod and note the keyring gap.

## Affected files summary

`multi-agent-shell/Dockerfile`, `multi-agent-shell/README.md`,
`multi-agent-shell/rootfs/etc/profile.d/50-multi-agent-shell-motd.sh`,
`multi-agent-shell/tests/test_motd.bats`,
`docs/standards/multi-harness-shells.md`,
`infra-shell/rootfs/etc/profile.d/50-infra-shell-motd.sh`,
`infra-shell/README.md`, `infra-shell/tests/*` (if present),
`README.md`, `.github/workflows/build.yaml`.
