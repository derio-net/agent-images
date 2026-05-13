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
   `tick()`. The bridge gains a new path for v2-plan Issues that
   delegates to the library.

This plan integrates the live bridge with the new library and ships
the image bump that rolls the pod onto it.

## Architecture

### Phase 1 — Additive integration (scope revised after agent audit on Issue #61)

The bridge actually does **873 LOC of application logic** — far more
than the GH-Issue parsing + state machine the original plan estimated
at ~600 lines. The full production surface includes:

- workspace creation + linking (`start_workspace`, `link_workspace_issue`)
- PR-status polling (In progress → In review → Done on merge)
- orphan workspace reaping
- lifecycle-transition shell hook
- max-concurrency slot accounting + dedup-by-title
- Pushgateway metrics / heartbeat
- dynamic repo discovery + gh-error log-level classification

This is locked in by **1621 LOC of tests (100 cases)** at
`kali/tests/test_vk_issue_bridge.py`. `vk.bridge.tick` (v2.1.0) only
covers observe → render → diff → apply → MCP `create_card` for phases
labelled `vk-ready`. None of the application logic above lives in the
library.

**Decision (Option 1):** Phase 1 is an **additive** refactor. Wire
`vk.bridge.tick` as the new card-creation path for v2-plan Issues
while keeping the existing main loop, parsers, workspace pipeline,
and metrics in place. Removing legacy logic is a follow-on rework
once the new path is proven in production (Phase 3) — not in this
plan.

The MCP adapter is non-trivial.
`vk.bridge.VkMcpClient.create_card(*, title, body, issue_url) -> str`
does NOT map structurally to the existing
`VkMcpClient.create_issue(project_id, title, **kwargs)`. The adapter's
`create_card` performs the full sequence currently in `sync_issue`:
create_issue → set status → list_repos → start_workspace →
link_workspace_issue.

Characterisation tests at the start of Phase 1 lock in the current
behaviour. The new library-delegation tests cover the additive path;
the existing 100 tests stay green throughout — those are the
regression net.

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
