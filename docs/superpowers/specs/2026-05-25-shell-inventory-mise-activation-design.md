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

Added step (per shell, paths/names adjusted for ruflo):

```bash
# Two-arm regression guard (issue #56): a populated inventory on a fresh PV
# must reconcile clean. Pre-fix this produced npm EACCES (shim fell through to
# /usr/bin/npm) and could regress YAML parsing once python@ activated.
docker exec paperclip-shell-smoke sh -c 'cat >/tmp/inv.yaml' <<'YAML'
mise:
  - node@20
npm-global:
  - "@anthropic-ai/claude-code"
pipx:
  - tldr
YAML
out=$(docker exec -e INVENTORY=/tmp/inv.yaml paperclip-shell-smoke \
        /usr/local/bin/paperclip-shell-reconcile)
echo "$out"
echo "$out" | grep -q 'failed=0'                       # arm 1: shim dispatches, no EACCES
! echo "$out" | grep -qi "No module named 'yaml'"      # arm 2: parsing stayed on system python
```

**Live-arm scope:** node@20 + an npm global (the issue's exact reproduction) + a
pipx package. Rust/cargo is excluded to avoid multi-minute toolchain pulls + crate
compiles on every push — the cargo loop shares the identical fall-through cause as
npm, so the node arm proves the mechanism. A hermetic stub test covering the cargo
path without CI cost is a possible follow-up, not built here.

## Acceptance

- [ ] Clean reconcile on a fresh PV with a populated inventory produces `failed=0`,
      for both paperclip-shell and ruflo-shell.
- [ ] No `ModuleNotFoundError: No module named 'yaml'` regression.
- [ ] CI smoke test (the extended docker jobs) exercises the activate + npm-global
      + YAML-parse path end-to-end, on both shells.

## Out of scope

- Deduplicating the two `install-inventory.sh` copies into one source of truth.
- Live cargo/rust coverage in CI (cost); optional hermetic stub follow-up.
