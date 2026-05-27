# Activate mise runtimes after install — implementation narrative

## Why

`install-inventory.sh` materializes mise runtimes with `mise install <tool>` but
never `mise use -g <tool>`. `mise install` only unpacks a runtime under
`~/.local/share/mise/`; it is `mise use -g` that records the active version in
`~/.config/mise/config.toml` so the per-binary shim knows what to dispatch to.
Without activation the shim silently falls through to the system binary
(`/usr/bin/npm`, prefix `/usr`, root-owned) — and the script's own
`export PATH=".../mise/shims:..."` makes that fall-through look legitimate right
up until the npm-global / cargo loops hit `EACCES` writing into `/usr/lib`.

The two arms are coupled: activating runtimes includes `python@`, after which the
script's own bare `python3` (used to parse the inventory YAML) resolves to mise's
PyYAML-less Python — a `No module named 'yaml'` regression. The fix activates
runtimes *and* pins YAML parsing to `/usr/bin/python3`, finally matching the
promise already written in the file's header comment.

The bug is duplicated verbatim in `ruflo-shell`, so the fix lands in both.

## Shape of the change

One phase, single repo (`derio-net/agent-images`). Three files change:

- `paperclip-shell/.../install-inventory.sh` — arm 1 (unconditional `mise use -g`
  after the install if/else) + arm 2 (`/usr/bin/python3` in both yaml helpers).
- `ruflo-shell/.../install-inventory.sh` — the same two edits, mirrored. Ruflo's
  older `run()` is left alone; converging the scripts beyond this bug is out of
  scope.
- `.github/workflows/build.yaml` — the `smoke-test-paperclip-shell` and
  `smoke-test-ruflo-shell` jobs each gain a populated-inventory reconcile after
  their existing empty-inventory boot assertions.

## Verification — local red → green

The only test is the docker e2e (the spec ruled out hermetic stub tests), so we
prove it the honest way: build paperclip-shell from the *unfixed* tree, run the
reconcile by hand, and confirm it goes RED with the exact EACCES / PyYAML failure;
apply the fix, rebuild, confirm GREEN. Because `BASE_SHA=latest` pulls the
prebuilt agent-shell-base from ghcr and only the thin paperclip layer rebuilds,
the loop is fast.

The inventory choice is load-bearing and identical everywhere it appears
(local checks and both CI jobs):

- `is-odd` as the npm package — guaranteed absent from the image, so the install
  path actually runs. `@anthropic-ai/claude-code` is baked into the system prefix
  (`base/Dockerfile:40`) and would short-circuit the loop to `already`, proving
  nothing.
- `python@3.12` in the mise list — the only way to make arm 2's regression fire,
  since it requires an *active* mise Python to shadow `/usr/bin/python3`.

The assertion `grep -q '✓ npm i -g is-odd'` is a single positive check that
catches *both* arms breaking: a broken arm 1 turns it into `✗ … EACCES`, and a
broken arm 2 empties the parsed list so the line never appears at all.

Ruflo is green-verified locally rather than red→green'd — the bug and mechanism
are identical to paperclip, already demonstrated. CI guards both shells on every
push thereafter.

## Spec

`docs/superpowers/specs/2026-05-25-shell-inventory-mise-activation-design.md`
(issue [#56](https://github.com/derio-net/agent-images/issues/56)).
