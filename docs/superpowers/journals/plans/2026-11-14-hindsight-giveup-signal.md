<!-- fr:journal-schema=4 -->
# Journal: 2026-11-14-hindsight-giveup-signal

<!-- fr:journal kind=discovery scope=plan id=p1-ci-yaml-unproven created=2026-11-14T21:42:45+00:00 phase=1 -->
### p1-ci-yaml-unproven · discovery · CI smoke steps are parse-validated only (phase 1)

Tasks 7.S1/S2 were validated by YAML parse (pyyaml via uv --with); the docker behaviour is proven only by a dispatched branch build. shellcheck was run on all new/changed scripts and is clean.

<!-- fr:journal kind=discovery scope=plan id=no-refactor-p1-t3 created=2026-11-14T21:42:45+00:00 phase=1 -->
### no-refactor-p1-t3 · discovery · no-refactor-because P1.T3 (phase 1)

halt-container is a 6-line script; nothing to clean

<!-- fr:journal kind=discovery scope=plan id=no-refactor-p1-t4 created=2026-11-14T21:42:45+00:00 phase=1 -->
### no-refactor-p1-t4 · discovery · no-refactor-because P1.T4 (phase 1)

finish change was a message swap plus one call; nothing to clean

<!-- fr:journal kind=discovery scope=plan id=no-refactor-p1-t5 created=2026-11-14T21:42:45+00:00 phase=1 -->
### no-refactor-p1-t5 · discovery · no-refactor-because P1.T5 (phase 1)

single short cont-init script; nothing to clean

<!-- fr:journal kind=discovery scope=plan id=no-refactor-p1-t7 created=2026-11-14T21:42:45+00:00 phase=1 -->
### no-refactor-p1-t7 · discovery · no-refactor-because P1.T7 (phase 1)

YAML-only CI steps; nothing to clean

<!-- fr:journal kind=finding scope=plan id=p1-r1 created=2026-11-14T21:49:09+00:00 phase=1 state=open review_scope=in -->
### p1-r1 · finding [open] (reviewer: in scope) · Pre-flight CI step asserts only ExitCode != 0; the spec said it must equal the recorded stage-2 code (phase 1)

Verified: the stage-2 failure code of s6-overlay 3.2.3.2 cannot be known offline, so the spec's 'equals the recorded code' was circular. The spec is amended to say non-zero and printed, with the observed value recorded in the PR body from the branch build.

<!-- fr:journal kind=finding scope=plan id=p1-r2 created=2026-11-14T21:49:09+00:00 phase=1 state=open review_scope=in -->
### p1-r2 · finding [open] (reviewer: in scope) · Identity tests lack the 'pg_controldata exits 0 with no identifier' case (phase 1)

Verified: the ctl_rc=1 case still printed an id. Added a {ctl_id: ''} case to test_unreadable_halts_and_never_execs.

<!-- fr:journal kind=finding scope=plan id=p1-r3 created=2026-11-14T21:49:09+00:00 phase=1 state=open review_scope=in -->
### p1-r3 · finding [open] (reviewer: in scope) · The chmod test skips missing scripts and matches a path anywhere in the Dockerfile (phase 1)

Verified (test_hindsight_halt.py:44-49). It now parses the chmod +x list, requires every script to exist, and covers finish and hindsight-api/run too.

<!-- fr:journal kind=finding scope=plan id=p1-r4 created=2026-11-14T21:49:09+00:00 phase=1 state=open review_scope=in -->
### p1-r4 · finding [open] (reviewer: in scope) · finish has un-rewrapped long lines after the #170 edit (phase 1)

Verified: lines 16, 52 and 54 were over 100 chars. Re-wrapped.

<!-- fr:journal kind=finding scope=plan id=p1-r5 created=2026-11-14T21:49:09+00:00 phase=1 state=open review_scope=in -->
### p1-r5 · finding [open] (reviewer: in scope) · The identity check discards stderr, so the halt reason lacks the cause (phase 1)

Verified (2>/dev/null on both tools). Each tool's stderr now goes to a temp file and its first 300 bytes go into the halt reason. If mktemp fails, errf falls back to /dev/null so the identity check can't false-halt. New test_unreadable_reason_carries_the_tool_stderr.

<!-- fr:journal kind=review scope=plan id=review-phase1-1 created=2026-11-14T21:49:09+00:00 phase=1 -->
### review-phase1-1 · review · Phase 1 review: 5 minor in-scope findings, all fixed (phase 1)

Independent reviewer over git diff f46346b..HEAD against spec R1-R4/R7 and plan 01.yaml. No blocking issues: bash rc capture is correct, there is no exec fall-through, the s6 halt/exitcode semantics hold, the CI smoke steps are sound, and #160 does not regress. Findings p1-r1..p1-r5 were raised and all fixed (r1 by spec amendment). After the fixes, 151 tests pass and shellcheck is clean.

<!-- fr:journal kind=lens scope=plan id=lens-errors-1 created=2026-11-14T21:49:09+00:00 phase=1 lens=errors step=review-phase -->
### lens-errors-1 · lens · Confirm on a real branch build the s6 exit code for a cont-init failure and that halt from finish keeps 125 (reviewer's s6-exit-code lens) (phase 1)

<!-- fr:journal kind=finding scope=plan id=p1-r1-resolved created=2026-11-14T21:49:09+00:00 phase=1 state=fixed resolves=p1-r1 -->
### p1-r1-resolved · finding [fixed] · resolves p1-r1: Pre-flight CI step asserts only ExitCode != 0; the spec said it must equal the recorded stage-2 code (phase 1)

Spec Design §Port pre-flight and the Tests paragraph now say non-zero and printed. The PR body records the observed value.

<!-- fr:journal kind=finding scope=plan id=p1-r2-resolved created=2026-11-14T21:49:09+00:00 phase=1 state=fixed resolves=p1-r2 -->
### p1-r2-resolved · finding [fixed] · resolves p1-r2: Identity tests lack the 'pg_controldata exits 0 with no identifier' case (phase 1)

Added the {ctl_id: ''} case.

<!-- fr:journal kind=finding scope=plan id=p1-r3-resolved created=2026-11-14T21:49:09+00:00 phase=1 state=fixed resolves=p1-r3 -->
### p1-r3-resolved · finding [fixed] · resolves p1-r3: The chmod test skips missing scripts and matches a path anywhere in the Dockerfile (phase 1)

The test parses the chmod +x list and requires every script to exist.

<!-- fr:journal kind=finding scope=plan id=p1-r4-resolved created=2026-11-14T21:49:09+00:00 phase=1 state=fixed resolves=p1-r4 -->
### p1-r4-resolved · finding [fixed] · resolves p1-r4: finish has un-rewrapped long lines after the #170 edit (phase 1)

Re-wrapped.

<!-- fr:journal kind=finding scope=plan id=p1-r5-resolved created=2026-11-14T21:49:09+00:00 phase=1 state=fixed resolves=p1-r5 -->
### p1-r5-resolved · finding [fixed] · resolves p1-r5: The identity check discards stderr, so the halt reason lacks the cause (phase 1)

stderr is captured into the halt reason, with a /dev/null fallback and a test.

<!-- fr:journal kind=discovery scope=plan id=p2-record-not-written created=2026-11-14T21:54:26+00:00 phase=2 -->
### p2-record-not-written · discovery · Executor returned done but never wrote its step record; the orchestrator wrote it from the return (phase 2)

The executor's return claimed the record was committed, but no file existed. The orchestrator wrote this record from the return's ticks and refactor reason. The code commits 6958512 (red) and ecd0a1a (green, README) and the suite log, 70 passed with exit=0 and written after ecd0a1a, are the executor's own.

<!-- fr:journal kind=discovery scope=plan id=no-refactor-p2-t1 created=2026-11-14T21:54:26+00:00 phase=2 -->
### no-refactor-p2-t1 · discovery · no-refactor-because P2.T1 (phase 2)

Test-only task: renames, inversions and explicit end_session False args. No production code to clean, and the tests follow the file's existing harness helpers.
