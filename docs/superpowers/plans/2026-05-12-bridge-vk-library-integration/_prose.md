# Bridge → `vk.bridge` Library Integration

**Sibling of:** `derio-net/superpowers-for-vk` rework
`docs/superpowers/plans/2026-05-09-vk-v2-library-rework-1/`

**Why this exists.** The original vk-v2-library plan
(`derio-net/superpowers-for-vk`) was scoped to a single repo and never
shipped the `vk.bridge.*` library described in spec
`2026-05-06-vk-rebuild-state-machine-design.md` lines 560-577. The
bridge here at `kali/scripts/vk-issue-bridge.py` has been maintaining
its own copies of `parse_issue_body`, `parse_dependencies`, and the
reconcile loop.

The sibling rework in superpowers-for-vk ships v2.1.0 with two changes:

1. Renderer translates `- Blocked by #N` so `N` is a tracking Issue
   number, not a phase number. (Today's bridge silently mis-gates
   any v2 plan with cross-phase deps because phase number leaks
   through.)
2. New `vk.bridge` sub-package exposing `discover_plans()` and
   `tick()`. The bridge becomes a thin wrapper.

This plan refactors the live bridge to consume the new library and
ships the image bump that rolls the pod onto it.

## Architecture

### Phase 1 — Refactor

The bridge currently does ~600 lines of GH-Issue parsing + state
machine work. After this phase it's down to a `main()` that
discovers plans per repo and calls `vk.bridge.tick()`. The MCP
client stays where it is — only an adapter is needed because
`vk.bridge.VkMcpClient` is a Protocol the existing client should
satisfy structurally.

Characterisation tests at the start of Phase 1 lock in the current
behaviour. The refactor must preserve every behaviour they assert.

### Phase 2 — Integration test

A real v2 plan fixture with cross-phase deps, dispatched through
`vk.bridge.tick()` against a stub GhClient + stub MCP. Asserts
that Phase 2's created Issue body has the correct `Blocked by #N`
reference (using the predecessor's actual Issue number, not the
phase number). This is the regression guard against the bug the
v2.1.0 renderer fix addressed.

### Phase 3 — Roll the pod

Manual: build + push secure-agent-kali, bump the manifest in frank,
watch one tick complete in production. Pass requires `errors=0`
in the first post-roll tick's TickResult.

## Dependencies

This plan depends on v2.1.0 of `vk` being installable from
GHCR / PyPI. Phase 1 starts after the superpowers-for-vk PR
tags v2.1.0.
