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

<!-- fr:journal kind=finding scope=plan id=p2-r1 created=2026-11-14T21:56:48+00:00 phase=2 state=open review_scope=in -->
### p2-r1 · finding [open] (reviewer: in scope) · README cost paragraph omits that claude's near-limit auto-compact still runs under the fence (phase 2)

Verified (README.md:271). The spec's Conversation cost says auto-compact remains, and R6 asks for the compaction cost to be documented.

<!-- fr:journal kind=finding scope=plan id=p2-r2 created=2026-11-14T21:56:48+00:00 phase=2 state=open review_scope=in -->
### p2-r2 · finding [open] (reviewer: in scope) · CLI leg of test_every_path_ends_session_by_default asserts membership, not the exact kill list (phase 2)

Verified (test_agent_session.py:882). It would still pass if the CLI killed extra sessions.

<!-- fr:journal kind=finding scope=plan id=p2-r3 created=2026-11-14T21:56:48+00:00 phase=2 state=open review_scope=out -->
### p2-r3 · finding [open] (reviewer: out of scope) · ensure_session() runs outside _send_locked's try/finally, so a failure there is unfenced although the README says the fence covers a failure before submit (phase 2)

Pre-existing: the ordering and the README claim come from #164, and this change does not alter where ensure_session runs.

<!-- fr:journal kind=finding scope=plan id=p2-r4 created=2026-11-14T21:56:48+00:00 phase=2 state=open review_scope=out -->
### p2-r4 · finding [open] (reviewer: out of scope) · A non-object JSON body crashes send() with AttributeError and no HTTP response (phase 2)

Pre-existing: send() indexed req['session_id'] before this change. The removed isinstance guard only protected the /v1 defaulting step.

<!-- fr:journal kind=review scope=plan id=review-phase2-1 created=2026-11-14T21:56:48+00:00 phase=2 -->
### review-phase2-1 · review · Phase 2 review: 2 minor in-scope findings fixed, 2 pre-existing filed out of scope (phase 2)

Independent reviewer over git diff 79d2080..ecd0a1a against spec R5-R6 and plan 02.yaml. Every send path fences by default, and only JSON false disables it. Nothing else depended on the removed serve() defaulting, idempotency cache included. All six spec-listed tests are handled, and fresh is unchanged. The full suite gave 70 passed. Findings p2-r1 and p2-r2 (in) are fixed; p2-r3 and p2-r4 (out) are pre-existing. The reviewer's suggested consumer-migration concern is already covered by Test Plan row 2 and the frank#990 heads-up.

<!-- fr:journal kind=finding scope=plan id=p2-r1-resolved created=2026-11-14T21:56:48+00:00 phase=2 state=fixed resolves=p2-r1 -->
### p2-r1-resolved · finding [fixed] · resolves p2-r1: README cost paragraph omits that claude's near-limit auto-compact still runs under the fence (phase 2)

The README now says claude's near-limit auto-compact still runs.

<!-- fr:journal kind=finding scope=plan id=p2-r2-resolved created=2026-11-14T21:56:48+00:00 phase=2 state=fixed resolves=p2-r2 -->
### p2-r2-resolved · finding [fixed] · resolves p2-r2: CLI leg of test_every_path_ends_session_by_default asserts membership, not the exact kill list (phase 2)

The CLI leg asserts the exact list [legacy-sess, run-123, cli-sess].

<!-- fr:journal kind=finding scope=plan id=p2-r3-resolved created=2026-11-14T21:56:48+00:00 phase=2 state=open resolves=p2-r3 out_of_scope=true -->
### p2-r3-resolved · finding [out-of-scope] · resolves p2-r3: ensure_session() runs outside _send_locked's try/finally, so a failure there is unfenced although the README says the fence covers a failure before submit (phase 2)

Predates this change (#164's ordering). It is not caused by flipping the default, so it gets filed as a follow-up.

<!-- fr:journal kind=finding scope=plan id=p2-r4-resolved created=2026-11-14T21:56:48+00:00 phase=2 state=open resolves=p2-r4 out_of_scope=true -->
### p2-r4-resolved · finding [out-of-scope] · resolves p2-r4: A non-object JSON body crashes send() with AttributeError and no HTTP response (phase 2)

Predates this change. send() crashed on non-object bodies before the /v1 guard was removed, so it gets filed as a follow-up.
