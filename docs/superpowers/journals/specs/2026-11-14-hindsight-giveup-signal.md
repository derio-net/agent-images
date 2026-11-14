<!-- fr:journal-schema=4 -->
# Journal: 2026-11-14-hindsight-giveup-signal

<!-- fr:journal kind=discovery scope=spec id=operator-brief created=2026-11-14T21:23:05+00:00 input=true -->
### operator-brief · discovery · Operator brief: batch hindsight-giveup-signal (agent-images#170)

/fr-goal hindsight give-up visible, legacy agent-session fenced, fresh adopted, version strings

Batch `hindsight-giveup-signal` of derio-net/agent-images: 1 issues, delivered as ONE pull request.

## agent-images#170: Leftovers: hindsight gives up silently, legacy agent-session path unfenced, fresh unadopted, stale 0.8.4 strings
hindsight gives up on postgres silently (container stays Ready, no /health signal); legacy agent-session send path unfenced (#152); fresh unadopted by frank; stale 0.8.4 strings.

## Why these belong together
Hindsight gives up on postgres while the container stays Ready; the other items are the same image's leftovers.

## Delivery rules
- Work on branch `feat/batch-hindsight-giveup-signal`.
- Open a draft PR as soon as the spec is committed. Its body contains these lines, one per member, so every member closes when it merges:
  Closes derio-net/agent-images#170
- Start the run (`fr run start` with `--issue 170`) so it records its issue.
- Do not name any member issue as a phase `tracking_issue` in the plan: the bridge would then own that issue's `fr:` labels.

Never add the `approved-fr` label: it is the operator's approval to merge, and fr voids it on your next push.

--- Issue #170 body ---
Found by the 2026-10-13 audit of merged derio-net batches. Leftovers of hindsight-pg-backoff (#163), agent-session-once (#164) and hindsight-offline-smoke (#168). The issues closed with these unmet, and nothing was filed.

## Defects
1. **#160: giving up is silent.** After postgres gives up (`hermes-agent-shell-hindsight/rootfs/etc/services.d/postgres/finish`, exit 125), the container stays Ready, and hindsight-api still trusts host:port and would connect to a foreign postgres. The PR listed these as "Out of scope": surface the failure on `/health`; fail readiness; check postgres identity before connecting; a port pre-flight at cont-init.
2. **#152: the duplicate-turn fence covers only `/v1/session/send`.** The legacy `/session/send` and the CLI default to off (`multi-agent-shell/rootfs/usr/local/lib/multi-agent-shell/agent-session`, `serve()`; `test_v1_ends_session_by_default_legacy_path_does_not`). The persistent-conversation consumers the PR names (frank alert-agent, n8n) can still get a self-resumed duplicate turn. The PR also says the original root cause is "most likely, not confirmed".
3. **#157: no consumer adopted `fresh`.** frank `apps/alert-agent` never passes `fresh`, so the frank#599 context-bleed class is mitigated only by frank#695's session-id split. File or do the frank-side change.
4. **Stale version strings.** These still say 0.8.4 while the Dockerfile pins 0.8.5: `README.md:29`, the Dockerfile comment at line 15, and `rootfs/etc/services.d/hindsight-api/run:2`.
5. **Housekeeping:** #164 adopted the version-sweep (#155) and hermes-ssh (#158) plan cursors at "implement pending", with manual phases unchecked. Reconcile them.

## Acceptance
- With postgres given up, `/health` reports it and the container is not Ready (test).
- The legacy send path and the CLI fence the turn too, or the decision not to is recorded with the remaining risk.
- frank's alert-agent passes `fresh` (or an issue there tracks it).
- No 0.8.4 string remains.

<!-- fr:journal kind=discovery scope=spec id=health-already-db-aware created=2026-11-14T21:23:05+00:00 -->
### health-already-db-aware · discovery · Upstream /health already 503s on a dead DB; the Ready-while-broken case is a foreign postgres on 5433

hindsight-api-slim 0.8.5 `MemoryEngine.health_check` (engine/memory_engine.py:3265) runs SELECT 1 and `/health` returns 503 on failure; frank's hindsight sidecar startup/readiness/liveness probes all curl /health; hindsight-api/run never execs while pg_isready fails. So a down postgres already fails probes (slowly, via the 300s startup budget). What stays Ready is a foreign postgres on 127.0.0.1:5433 (frank's stray ssh-sidecar postgres, 2026-08-19): pg_isready passes and /health reports healthy from the wrong DB.

<!-- fr:journal kind=decision scope=spec id=giveup-identity-and-halt created=2026-11-14T21:23:05+00:00 decided_by=operator -->
### giveup-identity-and-halt · decision · Give-up: identity check + cont-init port pre-flight + halt the container on give-up

Question: what should the hindsight image do about give-up / a foreign postgres?
Answer (operator, Round 1 Q1): "Identity + halt" — hindsight-api/run compares system_identifier with pg_controldata of our PGDATA and refuses on mismatch; a cont-init pre-flight fails boot when 5433 is already taken; on give-up (exit 125) postgres/finish halts the container non-zero so kubelet's CrashLoopBackOff is the bounded visible signal.
Interprets #170's "/health reports it" as: /health never answers healthy from a given-up or foreign postgres (API not exec'd, or container exited).

<!-- fr:journal kind=decision scope=spec id=fence-on-everywhere created=2026-11-14T21:23:05+00:00 decided_by=operator -->
### fence-on-everywhere · decision · Fence: end_session defaults on for every send path and the CLI; explicit false opts out

Question: which default for the #152 post-turn fence on the legacy /session/send path and the CLI?
Answer (operator, Round 1 Q2): "Fence on everywhere" — legacy and CLI default end_session to true like /v1; callers wanting a warm REPL pass end_session:false. A duplicate side-effecting turn costs more than the cold-start latency.

<!-- fr:journal kind=decision scope=spec id=version-sweep-close-and-file created=2026-11-14T21:23:05+00:00 decided_by=operator -->
### version-sweep-close-and-file · decision · Housekeeping: close the version-sweep cursor, tick P7.T1.S2, file the omnictl discovery

Question: how to reconcile the stalled version-sweep run (hermes-ssh already archived by #175)?
Answer (operator, Round 1 Q3): "Close it + file omnictl" — tick phase 6 and P7.T1.S2 ("left at v0.45.1, server version not established"), file an issue for the real omnictl-to-server discovery, close the cursor and archive the plan in this PR.

<!-- fr:journal kind=decision scope=spec id=fresh-frank-issue created=2026-11-14T21:23:05+00:00 decided_by=operator -->
### fresh-frank-issue · decision · fresh adoption: filed as derio-net/frank#990, not done here

Question: frank-side `fresh` adoption under the one-PR rule?
Answer (operator, Round 1 Q4): "File a frank issue" — filed as https://github.com/derio-net/frank/issues/990 (surge + digest orchestration sends pass fresh:true; chat bridge does not), which also warns of the fence default change.

<!-- fr:journal kind=decision scope=spec id=verification-pytest-branch-build-tester created=2026-11-14T21:23:05+00:00 decided_by=operator -->
### verification-pytest-branch-build-tester · decision · Verification: pytest + dispatched branch build pre-merge; frank boot post-merge, gate tester

Question: how is this run verified before merge, and who closes it out?
Answer (operator, Round 1 Q5): "pytest + branch build, tester" — local pytest suite plus a dispatched build.yaml branch build whose hindsight smoke jobs gain pre-flight and give-up-halts cases; rows `verify: none` with that reason; Test Plan rows for the frank sidecar boot and agent-session resume after the bump; gate: tester.

<!-- fr:journal kind=lens scope=spec id=lens-errors-1 created=2026-11-14T21:23:05+00:00 lens=errors step=brainstorm -->
### lens-errors-1 · lens · New halt/refuse paths in s6 scripts: every failure must exit loudly with the right code, never hang or silently exec

<!-- fr:journal kind=finding scope=spec id=f-1 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-1 · finding [open] (reviewer: in scope) · Changing the fence default breaks at least six existing tests, and the spec names only one

check: consistency · target: spec. The Design names only test_v1_ends_session_by_default_legacy_path_does_not (test_agent_session.py:864). These also break under `is not False`: test_cli_send_keeps_session_by_default (:858), test_flags_require_json_true (:915), test_live_existing_session_is_reused (:388), test_slow_live_existing_session_reused (:405), test_absent_session_still_creates (:421), test_compacts_when_context_over_threshold (:587; agent-session:672 skips /compact). Fix: list each test, pass end_session False where a test pins warm reuse or compaction, invert the ones that pinned the old default, and split :915.

<!-- fr:journal kind=finding scope=spec id=f-2 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-2 · finding [open] (reviewer: in scope) · Turning the fence on by default makes non-claude agents lose their conversation on every turn, which contradicts R5

check: codebase · target: spec. agent-session:182-187 uses --resume only for claude; multi-agent-shell/README.md:263-264 says the same. R5 claims the conversation always resumes. Fix: limit the claim to claude and document the non-claude cost.

<!-- fr:journal kind=finding scope=spec id=f-3 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-3 · finding [open] (reviewer: in scope) · The README rewrite misses two lines that become false

check: consistency · target: spec. multi-agent-shell/README.md:239-240 (legacy alias "differs only in the end_session default") and :272-273 ("only true enables") would contradict the new default. Add both to the rewrite.

<!-- fr:journal kind=finding scope=spec id=f-4 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-4 · finding [open] (reviewer: in scope) · The halt helper is hard-coded to an absolute path, but the bash-run unit tests need to stub it

check: consistency · target: spec. scripts/tests/test_hindsight_pg_backoff.py:66-70,82-89 run finish and run on the host, where /usr/local/lib/hindsight/halt-container and /run/s6/basedir/bin/halt do not exist. Fix: add a ${HINDSIGHT_HALT:-...} seam and S6_RESULTS_DIR/halt overrides, a unit test for the helper, and the helper in the Dockerfile chmod list (:132-137).

<!-- fr:journal kind=finding scope=spec id=f-5 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-5 · finding [open] (reviewer: in scope) · Rollout risk on frank. If the stray 5433 postgres is still there, the bump crash-loops the sidecar, and recent memories may live in the stray database

check: consistency · target: spec. The Context quotes frank's note that a stray postgres has held 5433 since 2026-08-19, and the Test Plan expects Ready after the bump. Fix: add a pre-bump operator precondition: check the holder, dump what hindsight wrote to it into our PGDATA, then stop it.

<!-- fr:journal kind=finding scope=spec id=f-6 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-6 · finding [open] (reviewer: in scope) · The R4 design says the Test Plan exercises it on frank, but no Test Plan row covers a given-up or foreign postgres

check: consistency · target: spec. An internal contradiction. Fix: point R4 at the smoke step and the unit tests, or add a row.

<!-- fr:journal kind=finding scope=spec id=f-7 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-7 · finding [open] (reviewer: in scope) · The pre-flight does not go through halt-container, so "every path uses it" is false and the exit code is s6's choice, not ours

check: consistency · target: spec. The pre-flight exits 1 and relies on S6_BEHAVIOUR_IF_STAGE2_FAILS=2 (agent-shell-base/Dockerfile:55). Fix: scope "every path" to the longruns, document that the exit code comes from s6, assert it via docker inspect, and pin N.

<!-- fr:journal kind=finding scope=spec id=f-8 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-8 · finding [open] (reviewer: in scope) · The identity-check commands need hardening so they cannot hang, prompt or misparse

check: codebase · target: spec. psql needs -w, PGCONNECT_TIMEOUT and -X; pg_controldata needs LC_ALL=C. Spell out the unreadable branch and exit after the halt, so the script never falls through to exec.

<!-- fr:journal kind=finding scope=spec id=f-9 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-9 · finding [open] (reviewer: in scope) · The version-string guard's pattern is ambiguous, and the guard passes vacuously when it finds nothing

check: codebase · target: spec. The forms differ: run:2 `hindsight-api-slim 0.8.4`, Dockerfile:15 `[local-ml] 0.8.4`, README:29 `[local-ml]==0.8.4`. Fix: specify the regex and require at least one match per file.

<!-- fr:journal kind=finding scope=spec id=f-10 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-10 · finding [open] (reviewer: in scope) · The setup for the give-up smoke step is underspecified

check: consistency · target: spec. A bad auto.conf needs an initialised cluster (30-hindsight-initdb:15-25). Fix: state how the cluster is initialised, assert ExitCode 125 via docker inspect, and don't use --rm.

<!-- fr:journal kind=finding scope=spec id=f-11 created=2026-11-14T21:32:40+00:00 state=open review_scope=in -->
### f-11 · finding [open] (reviewer: in scope) · In the version-sweep run, phase 6's implement unit is what is pending; the plan's phase 6 steps are already ticked

check: codebase · target: spec. 06.yaml:42-52 is already ticked; the run yaml shows phase/6/implement-phase pending and cursor implement. Fix: say so, and name docs/superpowers/implemented/plans/ as the archive destination.

<!-- fr:journal kind=review scope=spec id=spec-review-1 created=2026-11-14T21:32:40+00:00 -->
### spec-review-1 · review · Independent spec review: 11 findings, all in scope

Independent fr-spec-reviewer pass over the spec, the spec journal and the codebase. All 5 operator decisions are honoured; f-2 surfaces an unweighed cost of fence-on-everywhere for non-claude agents. The s6-overlay v3 halt/exitcode mechanism is correct and works rootless (agent-shell-base/Dockerfile:80-86 chowns /run). A failed cont-init under S6_BEHAVIOUR_IF_STAGE2_FAILS=2 stops the container before the longruns start. Findings raised: f-1..f-11, all in scope; the reviewer verified every file:line it cited. Suggested lenses: errors (already recorded), tests.

<!-- fr:journal kind=lens scope=spec id=lens-tests-1 created=2026-11-14T21:32:40+00:00 lens=tests step=spec-review -->
### lens-tests-1 · lens · The default flip inverts several existing agent-session tests (f-1); review the test edits as a whole

<!-- fr:journal kind=finding scope=spec id=f-1-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-1 -->
### f-1-resolved · finding [fixed] · resolves f-1: Changing the fence default breaks at least six existing tests, and the spec names only one

Design §agent-session Tests now lists every affected test: renames/inversions for :864/:858, the :915 split, explicit end_session:False for :388/:405/:421/:587, and a legacy twin for :925.

<!-- fr:journal kind=finding scope=spec id=f-2-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-2 -->
### f-2-resolved · finding [fixed] · resolves f-2: Turning the fence on by default makes non-claude agents lose their conversation on every turn, which contradicts R5

R5 now limits 'still resumes' to claude; Design §Conversation cost and R6 state that non-claude profiles start fresh each turn unless they send end_session:false. This stays within decision fence-on-everywhere, since frank's consumers all drive claude.

<!-- fr:journal kind=finding scope=spec id=f-3-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-3 -->
### f-3-resolved · finding [fixed] · resolves f-3: The README rewrite misses two lines that become false

The README rewrite now names :239-240 (legacy-alias line) and :272-273 (JSON-boolean rule) as well as :257-270.

<!-- fr:journal kind=finding scope=spec id=f-4-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-4 -->
### f-4-resolved · finding [fixed] · resolves f-4: The halt helper is hard-coded to an absolute path, but the bash-run unit tests need to stub it

Added seams HINDSIGHT_HALT, S6_RESULTS_DIR and S6_HALT, a unit test for the helper, and the helper in the chmod list; callers exit after halting.

<!-- fr:journal kind=finding scope=spec id=f-5-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-5 -->
### f-5-resolved · finding [fixed] · resolves f-5: Rollout risk on frank. If the stray 5433 postgres is still there, the bump crash-loops the sidecar, and recent memories may live in the stray database

Added a pre-bump Test Plan row (operator-driven, before frank's bump merges): check for a stray 5433 holder, dump and restore what hindsight wrote there, then stop it.

<!-- fr:journal kind=finding scope=spec id=f-6-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-6 -->
### f-6-resolved · finding [fixed] · resolves f-6: The R4 design says the Test Plan exercises it on frank, but no Test Plan row covers a given-up or foreign postgres

Dropped the 'Test Plan exercises R4 on frank' claim. R4 now points at the identity unit tests and the give-up smoke step, and the hindsight-giveup-halts verification line names R4.

<!-- fr:journal kind=finding scope=spec id=f-7-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-7 -->
### f-7-resolved · finding [fixed] · resolves f-7: The pre-flight does not go through halt-container, so "every path uses it" is false and the exit code is s6's choice, not ours

Halt-container is now scoped to the two longrun paths. The pre-flight exit code is documented as s6's stage-2 code, which the smoke step records via docker inspect, with N pinned at 60s.

<!-- fr:journal kind=finding scope=spec id=f-8-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-8 -->
### f-8-resolved · finding [fixed] · resolves f-8: The identity-check commands need hardening so they cannot hang, prompt or misparse

The identity check now uses psql -X -w with PGCONNECT_TIMEOUT=5 and LC_ALL=C pg_controldata. Non-zero exit or empty output is the unreadable branch, and exit follows the halt.

<!-- fr:journal kind=finding scope=spec id=f-9-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-9 -->
### f-9-resolved · finding [fixed] · resolves f-9: The version-string guard's pattern is ambiguous, and the guard passes vacuously when it finds nothing

The guard regex is now specified (extras optional, separator == or whitespace), with at least one match required per file.

<!-- fr:journal kind=finding scope=spec id=f-10-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-10 -->
### f-10-resolved · finding [fixed] · resolves f-10: The setup for the give-up smoke step is underspecified

The give-up smoke setup is specified: a first run initdbs and is stopped, then the bad GUC is appended as UID 1000, then a second run (not --rm) must reach ExitCode 125 within 150s with at most 6 failures.

<!-- fr:journal kind=finding scope=spec id=f-11-resolved created=2026-11-14T21:32:40+00:00 state=fixed resolves=f-11 -->
### f-11-resolved · finding [fixed] · resolves f-11: In the version-sweep run, phase 6's implement unit is what is pending; the plan's phase 6 steps are already ticked

Housekeeping now says the plan's phase 6 is already ticked. What remains is the run cursor's phase-6 unit, phase 7, journal-check and deliver; the archive target is docs/superpowers/implemented/plans/.

<!-- fr:journal kind=decision scope=spec id=exit-baseline created=2026-11-14T21:32:42+00:00 -->
### exit-baseline · decision · exit when spec-review resolved

The exit when spec-review resolved; `fr verification set` and `deliver` compare against it.

```yaml
row_gates:
  agent-session-fence-default: none
  hindsight-giveup-halts: none
  hindsight-identity-check: none
  hindsight-port-preflight: none
  hindsight-version-strings: none
row_kinds:
  agent-session-fence-default: none
  hindsight-giveup-halts: none
  hindsight-identity-check: none
  hindsight-port-preflight: none
  hindsight-version-strings: none
run_gate: tester
run_kind: none
```
