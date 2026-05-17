# ⚠️ ARCHIVED 2026-05-17 — see issue [derio-net/superpowers-for-vk#147](https://github.com/derio-net/superpowers-for-vk/issues/147)

This plan was the agent-images half (the bridge cron caller) of the
spec-dispatch design that lived in `superpowers-for-vk`. Never executed.
Archived because the 2026-05-17 bridge audit found that spec-dispatch
was patching around a more fundamental gap: v2 was supposed to deliver
a thin bridge but the bridge stayed fat (1089 lines, in this very
repo's `kali/scripts/vk-issue-bridge.py`). The real fix is the v2
bridge rebuild tracked in superpowers-for-vk#147.

Sibling spec + plan in superpowers-for-vk were archived in PR #148.

Original content preserved below.

---

# Plan — spec-dispatch-bridge (agent-images)

## What this plan delivers

The bridge cron caller change that makes the live VK bridge auto-advance
spec-level plan DAGs every tick. Sibling plan to
`2026-05-14-spec-dispatch` in superpowers-for-vk; together they implement
the spec at
`docs/superpowers/specs/2026-05-13-spec-dispatch-design.md` (which lives
in superpowers-for-vk).

Single phase, one PR — adds a `vk.bridge.discover_specs(repo)` →
`vk.spec.dispatch(spec, gh)` loop to the per-repo iteration in
`kali/scripts/vk-issue-bridge.py::main()`, placed BEFORE the existing
plan-tick loop so same-tick spec→plan handoff works (the spec dispatches
a plan's issues; the same iteration's `discover_plans` picks them up).

## Success criteria

After this plan ships:

- The bridge cron tick logs a `[bridge] spec dispatch: walked=… dispatched=…
  already=… blocked=… errors=…` summary line per tick.
- A spec whose root plan was complete on the previous tick gets its
  downstream plans dispatched on the next tick (issues created in the
  correct target repos via `gh issue create --repo <X>`).
- A spec whose Depends-on grammar is invalid logs a warning and the
  bridge continues to other specs / plans without crashing.
- A spec whose cross-repo plan files 404 logs the failure into the
  summary's `failures` list; the rest of the tick continues.
- Existing bridge behaviour (per-plan tick, vk-ready → vk-synced
  projection, MCP card sync) is unchanged.

## Prerequisites

This plan **depends on two upstream artifacts** that are not in this
spec's table because they live elsewhere:

1. **`2026-05-12-bridge-vk-library-integration` plan** (this repo).
   ✅ **Shipped** — Phase 3 closed 2026-05-15 in commit `dbcbc70`.
   The bridge daemon now imports `from vk import bridge as vk_bridge`
   and pre-binds `_DISCOVER_PLANS`/`_TICK` at module scope (see
   `kali/scripts/vk-issue-bridge.py:24-31`). `P1.T1.S1` of this plan
   re-greps to confirm before proceeding.

2. **superpowers-for-vk v2.2.0 installed in the bridge env.**
   ⏳ **Pending** — sibling plan `2026-05-14-spec-dispatch` (in
   `derio-net/superpowers-for-vk`) ships v2.2.0 with `vk.spec.dispatch`,
   `vk.bridge.discover_specs`, and `GhClient.read_repo_file`. The
   bridge env's current `vk` install is `git+...@v2.1.4` per
   `base/Dockerfile`; `P1.T1.S2` bumps the tag to `@v2.2.0`. The spec
   table's `Depends on` column for this plan lists
   `2026-05-14-spec-dispatch`.

Both prerequisites must be live before any code work in this plan
begins. The first task validates them with grep + a short import smoke
test.

## What this plan does NOT deliver

- The library and CLI surface (lives in the sibling plan
  `2026-05-14-spec-dispatch`).
- A bridge-side cache for cross-repo gh contents reads. The spec §2.3
  deferred this until quota becomes real; no caching in v1.
- Replacement of the bridge daemon's own gh subprocess wrappers with
  `GhClient`. Out of scope — that work belongs to the
  `bridge-vk-library-integration` plan above.

## Sequencing within agent-images

Single phase. The 5 tasks proceed top-to-bottom:

1. Verify prerequisites (no code changes).
2. Add the spec dispatch loop to the main per-repo iteration, with a
   failing test gating each step.
3. Add the `SpecDispatchSummary` accumulator and structured logging.
4. End-to-end integration test for the same-tick handoff.
5. Quality gates + PR.

## Cross-cutting principles preserved

- **No new state files in the bridge.** The summary lives in memory
  per tick; no `.bridge_state.json` or similar.
- **Fail-loud, isolate per spec.** A `SpecValidationError` from any
  one spec logs a warning and doesn't abort the loop; other specs
  and the plan-tick layer continue.
- **Shared primitive.** The bridge calls the same `vk.spec.dispatch()`
  function `vk spec apply` calls — no bridge-specific wrapper.
