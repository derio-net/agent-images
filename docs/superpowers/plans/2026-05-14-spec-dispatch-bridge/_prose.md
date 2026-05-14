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

## Prerequisites (load-bearing)

This plan **depends on two upstream artifacts** that are not in this
spec's table because they live elsewhere:

1. **`2026-05-12-bridge-vk-library-integration` plan** (this repo,
   `docs/superpowers/plans/2026-05-12-bridge-vk-library-integration/`).
   Migrates the bridge daemon to use `vk.bridge.tick` and
   `vk.bridge.discover_plans`. Today the bridge imports nothing from
   the `vk` package — it does its own gh subprocess wrapping. The first
   task in this plan (`P1.T1`) explicitly checks the migration has
   happened; if not, the agent STOPS and reports to the operator.

2. **superpowers-for-vk v2.2.0 installed in the bridge env.** The
   sibling plan `2026-05-14-spec-dispatch` releases v2.2.0 with the
   new `vk.spec.dispatch`, `vk.bridge.discover_specs`, and
   `GhClient.read_repo_file` surfaces this plan uses. The spec
   table's `Depends on` column for this plan therefore lists
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
