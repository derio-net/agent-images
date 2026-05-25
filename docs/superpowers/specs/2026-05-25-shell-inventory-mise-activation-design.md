# Shell inventory: activate mise runtimes after install

**Date:** 2026-05-25
**Issue:** [derio-net/agent-images#56](https://github.com/derio-net/agent-images/issues/56)
**Status:** Design approved — ready for planning

## Problem

`install-inventory.sh` installs mise runtimes with `mise install <tool>` but never
runs `mise use -g <tool>`. `mise install` only materializes a runtime under
`~/.local/share/mise/`; it is `mise use -g` that writes `~/.config/mise/config.toml`
so the per-binary shim knows which version to dispatch to. Without activation the
shim (`~/.local/share/mise/shims/npm`, `.../cargo`, …) has no active version and
**silently falls through to the system binary** (`/usr/bin/npm`, default prefix
`/usr`, root-owned). The `npm-global` and `cargo` loops later in the same script
then resolve against the wrong root-owned prefix and fail with `EACCES` — yet the
script's own `export PATH=".../mise/shims:..."` (line 31) makes the fall-through
look like the shim is in charge.

Reproduction (from the issue): a fresh-PV reconcile with `mise: [node@20]` +
`npm-global: ["@openai/codex"]` produces `npm error code EACCES` on
`mkdir /usr/lib/node_modules/@openai`. Operators currently work around it by
manually running `mise use -g node@20 rust@stable` over SSH and re-reconciling.

The two arms of the fix are coupled: activating runtimes includes `python@3.x`,
after which the YAML-parsing helpers' bare `python3` resolves to mise's
PyYAML-less Python — a `ModuleNotFoundError: No module named 'yaml'` regression.
The script's header comment already promises parsing uses `/usr/bin/python3`; the
implementation never delivered.

The bug is duplicated: `ruflo-shell` ships a near-identical `install-inventory.sh`
(slightly older — it lacks paperclip's hardened `run()` rc-capture and cargo
`awk`) carrying the same missing-activation bug.

## Scope

Fix **both** `paperclip-shell` and `ruflo-shell`. They share the identical bug;
fixing one leaves a known landmine in the other. The shared logic is **not**
deduplicated in this change (the scripts already differ in minor hardening; a
dedupe refactor is out of scope for a bugfix and tracked separately if wanted).

## Fix

Mirrored edits to:
- `paperclip-shell/rootfs/usr/local/lib/paperclip-shell/install-inventory.sh`
- `ruflo-shell/rootfs/usr/local/lib/ruflo-shell/install-inventory.sh`

### Arm 1 — Activate after install (mise section)

For each mise tool, install if missing, then run `mise use -g "$tool"`
**unconditionally** — on both the fresh-install and the already-present paths:

```bash
if mise where "$tool" >/dev/null 2>&1; then
    already+=1
    echo "= mise $tool"
else
    run "mise install $tool" mise install "$tool" && installed+=1
fi
# Activate unconditionally so the shim dispatches. Idempotent + cheap, and it
# heals PVs left half-configured by the pre-fix script (installed-but-unactivated).
run "mise use -g $tool" mise use -g "$tool"
```

Running activation unconditionally is deliberate: `mise use -g` is idempotent, and
a plain re-run must repair a volume that an operator hit the bug on without
requiring manual `mise use -g`. Activation failures flow through the existing
`run()` accumulator → counted in `failed`, surfaced via MOTD + Telegram, fail-open
preserved (`set -e` is intentionally off; script always `exit 0`).

### Arm 2 — Pin YAML parsing to system Python

`yaml_list` and `yaml_removed_list` change their bare `python3` invocation to
`/usr/bin/python3`, honoring the existing header comment. This is robust
regardless of inventory contents and lets `python@3.x` activate as a normal
operator runtime without breaking the script's own parsing.

### Implementation note for ruflo-shell

Mirror the *exact* if/else + unconditional-activation shape and the `/usr/bin/python3`
pin into ruflo's copy. Do **not** also "upgrade" ruflo's older `run()` (it lacks
paperclip's rc-capture comment and uses an `else` branch instead of post-`if` rc
capture) — that hardening is unrelated to issue #56 and would inflate the diff. Keep
the two scripts converging only on the bug being fixed here.

## Test — live docker e2e (node arm)

Extend the existing `smoke-test-paperclip-shell` and `smoke-test-ruflo-shell` jobs
in `.github/workflows/build.yaml`. **Keep** the current empty-inventory boot
assertions unchanged (they verify fast fail-open boot), then **append** a
populated-inventory reconcile against the still-fresh PV.

Why exec-after-boot rather than populate-at-boot: a non-empty inventory at boot
would run `mise install node@20` inside cont-init.d before sshd, coupling the 30s
sshd-up budget to install time (the kali job had to bump to 90s for this reason).
Booting empty keeps boot fast; the PV is genuinely fresh (empty inventory
installed nothing), so a subsequent reconcile with a populated inventory is a
faithful "clean reconcile on a fresh PV."

The `…-reconcile` command is a bare symlink to `install-inventory.sh` (Dockerfile
`ln -sf`), and the script reads `INVENTORY="${INVENTORY:-…}"` from env, so an
`INVENTORY` override passes through transparently — no wrapper to swallow it.

### Inventory choice is load-bearing (do not change casually)

The test inventory must force the *failing* paths, or it silently proves nothing:

- **npm package must NOT be baked into the image.** `base/Dockerfile:40` installs
  `@anthropic-ai/claude-code` via *system* npm into the root-owned global prefix
  (`/usr/lib/node_modules`), baked into the layer. The npm-global loop guards with
  `npm ls -g "$pkg" --depth=0 && continue` (`install-inventory.sh:112`): a baked
  package reports present even via `/usr/bin/npm`, so the loop short-circuits to
  `already` and **never runs `npm install -g`** — the EACCES path under repair is
  never reached, and the test passes green with the bug intact. We use a small
  package guaranteed absent from the image (`is-odd`) so the install actually
  executes against the active npm's prefix. The issue's repro used `@openai/codex`
  for the same reason; `is-odd` is the same idea, tiny and dependency-light.

- **inventory must include a `python@` mise entry.** Arm 2's regression only fires
  *after* a mise Python is active (it then shadows `/usr/bin/python3` for the
  script's own bare `python3` calls). With no `python@` in the inventory, the
  `! grep "No module named 'yaml'"` assertion is vacuous — it passes whether or not
  arm 2 is applied. Adding `python@3.12` makes the mise section activate Python
  *before* the npm-global section re-parses the inventory via `yaml_list`, which is
  exactly when unpinned code would error and silently return an empty package list.

### Added step (per shell, paths/names adjusted for ruflo)

```bash
# Two-arm regression guard (issue #56): a populated inventory on a fresh PV must
# reconcile clean. Pre-fix, arm 1 produced npm EACCES (mise shim fell through to
# /usr/bin/npm against the root-owned /usr prefix); arm 2 regressed once python@
# activated and the script's bare `python3` resolved to mise's PyYAML-less Python.
# Package choices are deliberate — see "Inventory choice is load-bearing".
docker exec paperclip-shell-smoke sh -c 'cat >/tmp/inv.yaml' <<'YAML'
mise:
  - node@20
  - python@3.12
npm-global:
  - is-odd
YAML
out=$(docker exec -e INVENTORY=/tmp/inv.yaml paperclip-shell-smoke \
        /usr/local/bin/paperclip-shell-reconcile 2>&1)
echo "$out"
# Arm 1 + arm 2 in one positive assertion: a ✓ install line proves (a) yaml
# parsing found the package — arm 2 didn't silently empty the list — AND (b) the
# active npm dispatched to a writable prefix without EACCES. Pre-fix this line is
# either `✗ npm i -g is-odd (rc=…)` (arm 1 broken) or absent entirely (arm 2 broke
# the parse, so the npm-global loop iterated zero times).
echo "$out" | grep -q '✓ npm i -g is-odd'
echo "$out" | grep -q 'failed=0'                       # overall clean reconcile
! echo "$out" | grep -qi "No module named 'yaml'"      # arm 2: no PyYAML traceback on stderr
```

`2>&1` on the `docker exec` is required: the arm-2 traceback and `mise`'s own
diagnostics go to stderr, and the script's `exec > >(tee -a "$LOG") 2>&1` already
merges them into the log — capturing stderr here keeps the captured `out` faithful
to what an operator sees. (If the `tee` subshell ever races process exit and
truncates the tail under `docker exec`, fall back to grepping the persisted log:
`docker exec … cat /var/log/cont-init.d/40-shell-inventory.log`.)

**Live-arm scope:** node@20 + python@3.12 (both prebuilt mise downloads, not
compiles) + one not-baked npm global. Rust/cargo is excluded to avoid multi-minute
toolchain pulls + crate compiles on every push — the cargo loop shares the
identical fall-through cause as npm, so the node arm proves the mechanism. A
hermetic stub test covering the cargo path without CI cost is a possible follow-up,
not built here.

## Acceptance

- [ ] Clean reconcile on a fresh PV with the test inventory above produces
      `failed=0` and a `✓ npm i -g is-odd` line (the install path actually ran and
      succeeded against a writable prefix), for both paperclip-shell and ruflo-shell.
- [ ] No `ModuleNotFoundError: No module named 'yaml'` regression, with `python@3.12`
      active in the inventory.
- [ ] CI smoke test (the extended docker jobs) exercises activate → npm-global
      install → YAML-parse-after-python-activation end-to-end, on both shells.

## Known limitations

- Unconditional `mise use -g "$tool"` makes the **last** entry win when an inventory
  lists two versions of the same plugin (e.g. `node@20` and `node@22`) — global
  activation is single-version per plugin. Current inventories list one version per
  plugin, so this isn't hit; documented here rather than discovered in production.

## Implementation Plans

| Plan | Repo | File | Depends on |
|------|------|------|------------|
| 2026-05-25-shell-inventory-mise-activation | `derio-net/agent-images` | `docs/superpowers/plans/2026-05-25-shell-inventory-mise-activation/` | — |

## Out of scope

- Deduplicating the two `install-inventory.sh` copies into one source of truth.
- Live cargo/rust coverage in CI (cost); optional hermetic stub follow-up.
- Hardening ruflo's older `run()` to match paperclip's (unrelated to #56).
