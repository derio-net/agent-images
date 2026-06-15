# Plan: Replace gemini CLI with antigravity CLI (`agy`) in multi-agent-shell

**Spec:** [`docs/superpowers/specs/2026-06-15-antigravity-cli-swap-design.md`](../../specs/2026-06-15-antigravity-cli-swap-design.md)
**Issue:** [#119](https://github.com/derio-net/agent-images/issues/119)

## Goal

Swap the deprecating **gemini CLI** for the **antigravity CLI** (`agy`) across
`multi-agent-shell` (and the references `infra-shell` inherits), before gemini
CLI is removed upstream (~2026-06-18). Harnesses become `claude`, `codex`,
`agy`, `opencode`.

## Why this is not a like-for-like rename

`agy` differs from gemini CLI in three load-bearing ways, all driving the plan:

1. **Binary-distributed, not npm.** Installed via `curl …/install.sh | bash`
   (binary `agy` → `~/.local/bin/agy`), not `npm i -g`. The Dockerfile gets a
   dedicated install RUN that relocates the binary to `/usr/local/bin/agy`
   (Phase 3), validated first by a spike (Phase 1).
2. **No self-update, no version pin.** `agy` has no `update` subcommand and the
   installer documents no pin. So `agy` is updated by **image rebuild** and is
   **not** an inventory `harnesses:` entry (spec deviation D1). It is removed
   from the inventory examples rather than renamed into them.
3. **Different auth UX + credential path.** Auth is interactive OAuth on first
   run of `agy` (no `agy login`, no API key). Credentials land at
   `~/.gemini/antigravity-cli/credentials.enc` (best-effort — spec risk R1,
   resolved post-merge). The MOTD detector gets an optional login-hint arg so
   the `✗ agy` line reads `run: agy` (Phase 2).

## Constraints (operator)

- **No API key in the environment** — persistent agents; never set
  `ANTIGRAVITY_API_KEY`. Subscription-OAuth only.
- **Auth is interactive** — human completes OAuth once per pod; creds persist
  on the PV.

## Phase map

| Phase | What | Depends on | Verified by |
|---|---|---|---|
| 1 | Spike: run the install script, confirm binary/path/version | — | observed `agy --version` |
| 2 | MOTD detector swap (TDD) — both MOTD scripts | — | bats RED→GREEN + shellcheck |
| 3 | Dockerfile install swap | 1 | grep-clean + lint (CI build is the real gate) |
| 4 | Manifest, standard, READMEs, inventory examples | 1 | grep-clean per file |
| 5 | CI smoke loops + residual-gemini sweep | 2,3,4 | grep sweep + full bats/shellcheck |

## TDD note

The genuinely unit-testable surface is the MOTD detector (Phase 2), driven
RED→GREEN via `multi-agent-shell/tests/test_motd.bats`. The Dockerfile change
has no local unit test — its gate is the CI `smoke-test-multi-agent-shell` /
`infra-shell` jobs (`agy --version` as UID 1000), since the devcontainer has no
docker-in-docker. Phase 1's spike de-risks the install command before it is
committed to the Dockerfile.

## Out of scope (left as historical record)

`docs/superpowers/specs/2026-05-12-agent-shells-batch-design.md` and
`docs/superpowers/plans/2026-06-01-agent-shells-batch/` keep their `gemini`
references — they record what was built then (spec deviation D2).

## Post-merge

A Test Plan (in the spec) is operator-driven after merge: build the image, run
`agy` interactively, complete OAuth, and confirm the real credential path —
resolving risk R1. If the path differs from
`~/.gemini/antigravity-cli/credentials.enc`, the fix is a one-line update to the
two MOTD scripts + the manifest row (they are coupled by design).
