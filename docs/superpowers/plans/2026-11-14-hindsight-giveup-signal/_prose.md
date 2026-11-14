# Hindsight give-up signal, the fence on by default, and #170's leftovers

Three agentic phases, one per independently reviewable ask:

1. **Hindsight (R1–R4, R7)** is the skeleton. Its first task is the smoke (the scripts
   suite green on a trivial test; the repo is `ci none`). It then adds the version-string
   guard, the `halt-container` helper with test seams, give-up halting, the cont-init port
   pre-flight, the postgres identity check and the two CI smoke steps. Every behaviour is
   unit-tested by running the real bash scripts with stubbed binaries, the harness style
   `scripts/tests/test_hindsight_pg_backoff.py` set. Docker isn't available locally, so the
   smoke steps are proven only by the dispatched branch build at deliver.
2. **agent-session (R5–R6)**: flip `end_session` to "only false disables" on every path,
   with the six existing tests the flip touches named explicitly (spec-review f-1), plus
   the README.
3. **Housekeeping (R8)**: close the stalled version-sweep cursor and plan, and file the
   omnictl discovery issue. Mechanical, docs-only.

Pre-merge verification beyond these phases: the operator-approved branch build
(`build.yaml` workflow_dispatch on this branch), run at deliver. It is not a plan step,
because it is verification, not implementation.
