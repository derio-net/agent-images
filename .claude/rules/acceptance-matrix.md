# Acceptance Matrix — Backfill Rule (repo-wide)

## Rule

The acceptance matrix is the registry of business-level acceptance tests ×
verification levels × automation status. Its rows live in **per-feature
fragments**, `docs/acceptance/features/<spec-slug>.yaml`: each row is owned by
the feature (spec) that created it, and `legacy.yaml` holds rows with no single
origin spec. The effective matrix is never stored — `fr` folds the fragments.
**Any PR that does one of the following updates the rows in the SAME PR:**

- adds or changes a spec `## Test Plan` (new spec ⇒ new rows; the CI
  staleness guard fails a spec with a Test Plan that no row cites)
- adds tests that verify an existing row (add the ref to `levels`, move
  `status` up: `not-implemented` → `unwired` → `ci`/`scheduled`)
- ships a surface or capability a `not-implemented` row waits on
- changes CI workflows that run matrix-referenced checks
- discovers a red acceptance: set `status: failing` — the
  `acceptance-report` workflow then FAILS by design until it is fixed or
  re-classified with reasoning in `notes`

Statuses move **explicitly, never silently**: `ci` | `scheduled` (automated
— the safe end) · `walked` (proven live, dated by its walk) · `manual` (a
process that is never automatable) · `unwired` (a test exists, not in CI —
debt) · `walk-owed` (a live or post-merge walk is owed — debt) ·
`not-implemented` (nothing exists — debt) · `failing` (fails CI).

## How

- Add rows: `fr acceptance add --id ... --capability ... --acceptance ...
  --origin spec:<slug>#R<n> --level unit=<repo>:<path>#<test> --status ...
  --notes ...` — the row lands in its origin spec's fragment (`--feature` names
  one for a row with no single origin spec). fr artifacts are cited logically
  (`spec:<slug>[#R<n>]`, `plan:<slug>`), so archiving never rewrites a row; code
  keeps `<repo>:<path>[#test]`.
- Move a row: `fr acceptance set-status --id ... --status ... --notes "<why>"`.
  Never hand-edit a fragment.
- Check: `fr acceptance check` (refs, staleness, statuses; exit 2 on
  `failing`). Nag: `fr acceptance status` — **any agent session in this repo
  runs `fr acceptance status --brief` at session start** (Claude Code does it
  automatically via the super-fr SessionStart hook; other harnesses honor
  this line).
- Reports are derived, never committed: `fr acceptance report` renders one
  locally.
- CI: none is configured. `fr acceptance check` runs locally, and no row may
  move to `ci` until the repo has a CI config (`fr acceptance init --with-ci`
  scaffolds one).
