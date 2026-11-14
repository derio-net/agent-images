# Hindsight give-up made visible, the duplicate-turn fence on by default, and #170's leftovers

Batch `hindsight-giveup-signal`, closing derio-net/agent-images#170. The batch collects
what #163 (hindsight-pg-backoff), #164 (agent-session-once) and #168
(hindsight-offline-smoke) left unmet when their issues closed.

## Context

### Hindsight: the real hole is a foreign postgres, not a silent give-up

#170 says that after postgres gives up (`hermes-agent-shell-hindsight/rootfs/etc/services.d/postgres/finish`,
exit 125) the container stays Ready. Reading the code and frank's manifest narrows that
claim:

- frank's hindsight sidecar runs `startupProbe`, `readinessProbe` and `livenessProbe`
  as `curl -sf http://127.0.0.1:8888/health`
  (frank `apps/hermes-agent-shell/manifests/deployment.yaml`, the `hindsight` container).
- Upstream `/health` (hindsight-api-slim 0.8.5, `hindsight_api/api/http.py` → `MemoryEngine.health_check`,
  `engine/memory_engine.py:3265`) runs `SELECT 1` and answers **503** when that fails.
- `services.d/hindsight-api/run` loops on `pg_isready` before it execs hindsight-api,
  so when our postgres is down at boot the API never binds. The startup probe then
  restarts the container, but only after its 300s budget.

So a postgres that is simply *down* already fails the probes, if slowly. The case that
really stays Ready is a **foreign** postgres on `127.0.0.1:5433`. That is exactly the
frank incident: a postgres started by hand in the ssh sidecar held 5433 in the shared pod
netns (frank deployment comment, "a manually-started postgres in the ssh sidecar has held
127.0.0.1:5433 since 2026-08-19"). `pg_isready` passes against it, hindsight-api connects
to it, `SELECT 1` succeeds, and `/health` reports healthy while reading and writing the
wrong database. Meanwhile our own postgres sits given-up behind it.

### The duplicate-turn fence covers only /v1

`multi-agent-shell/rootfs/usr/local/lib/multi-agent-shell/agent-session` reads
`end_session = req.get("end_session") is True` in `_send_locked`. Only `serve()` defaults
it on, and only for `/v1/session/send`. The legacy `/session/send` (frank's alert-agent
telegram bridge, `tg_bridge/bridge.py` `session_send`; n8n's agent-session driver) and the
`agent-session send` CLI therefore run without the fence. A background task that finishes
after the result file lands can still inject a self-initiated, side-effecting turn
(agent-images#152). The pinning test is `test_v1_ends_session_by_default_legacy_path_does_not`.
For claude, the fence keeps the conversation: `_end_session` kills the tmux session, the claude
transcript stays on the PVC, and the next send reopens it with `--resume`
(`launch_command`). What it costs is a claude cold start per turn, and no proactive
`/compact` (skipped when the session is about to end). The #152 root cause is still
recorded as "most likely, not confirmed"; the fence is the mitigation whatever the
trigger turns out to be.

### `fresh` has no consumer

No frank consumer passes `fresh` (#157). frank's alert-agent splits sessions per stream
(frank#695), but the surge stream re-wakes on a 6h cooldown, under the 12h idle reset, so
it can still see its previous wake's narrative. Under the one-PR rule this is frank-side
work, and it is filed as **derio-net/frank#990**, which also warns about the fence default
change below.

### Stale strings and a stalled cursor

`hermes-agent-shell-hindsight/README.md:29`, `Dockerfile:15` (comment) and
`rootfs/etc/services.d/hindsight-api/run:2` still say 0.8.4, while
`ARG HINDSIGHT_API_VERSION=0.8.5`. The hermes-ssh plan cursor (#158) is already archived
(#175). The version-sweep run `docs/superpowers/runs/2026-10-11-feat-upstream-version-sweep.yaml`
is still at `implement`, with phase 6's steps done at #155's merge and manual phase 7
(`omnictl` pin) unticked. `OMNICTL_VERSION` is still `v0.45.1`, which is exactly phase 7's
own fallback step P7.T1.S2.

## Requirements

R1. Before postgres starts, the hindsight container checks whether anything already accepts connections on 127.0.0.1:5433; if so it fails boot loudly, naming the port, and the container exits non-zero before any postmaster is started.
R2. hindsight-api starts only against our own postgres: before exec it compares the serving cluster's system identifier with the one in our PGDATA, and on a mismatch (or when it cannot read either) it refuses to start, says why, and halts the container non-zero.
R3. When postgres gives up (the #160 bounded backoff reaches its limit), the container exits non-zero instead of staying up with postgres down, so kubelet's restart backoff and the container's restart count are the visible signal; the backoff that prevents a fork storm is kept.
R4. With postgres given up or foreign, hindsight's `/health` never answers healthy: the API is either not serving or the container has exited.
R5. The post-turn fence ends the harness session by default on every send path, legacy `/session/send`, `/v1/session/send` and the `agent-session send` CLI; only an explicit JSON `false` for `end_session` keeps the session, and for claude the conversation still resumes on the next send (other agent profiles start fresh each turn unless they opt out).
R6. The README documents the new fence default, its cost (cold start per turn, no proactive compaction, no conversation continuity for non-claude agents) and the `end_session: false` opt-out.
R7. No `0.8.4` hindsight-api version string remains, and a test fails if a hindsight-api version mentioned in the image's README, Dockerfile comment or run script disagrees with `ARG HINDSIGHT_API_VERSION`.
R8. The version-sweep plan is reconciled: phase 6 is recorded as done at #155's merge, P7.T1.S2 is ticked ("omnictl left at v0.45.1: the Omni server version was not established"), the real omnictl-to-server discovery is filed as an agent-images issue, and the plan and its run cursor are closed out.

## Design

### Hindsight (R1–R4, R7)

A small shared helper, `/usr/local/lib/hindsight/halt-container <code> <reason>`, prints
the reason to stderr, writes `<code>` to `${S6_RESULTS_DIR:-/run/s6-linux-init-container-results}/exitcode`,
and runs `${S6_HALT:-/run/s6/basedir/bin/halt}`. That is s6-overlay v3's way for a service
to stop the container with a chosen exit code, and it works rootless because
agent-shell-base chowns `/run` to the agent UID (agent-shell-base/Dockerfile:80-86). Both
**longrun** paths (the identity check and the give-up) call it. Each calls it as
`"${HINDSIGHT_HALT:-/usr/local/lib/hindsight/halt-container}"`, a seam the bash-driven unit
tests stub, and then `exit`s with the same code, never falling through to an `exec`. The
helper is `chmod +x`'d in the Dockerfile with the other scripts and has its own unit test
(writes the code, calls the halt stub, prints the reason).

- **Port pre-flight (R1):** a new cont-init `35-hindsight-port-preflight` (after
  `30-hindsight-initdb`) probes `127.0.0.1:5433` with bash's `/dev/tcp`, bounded by
  `timeout 2`. If the port accepts a connection, it prints an error naming the port and
  exits 1. It deliberately does **not** call halt-container: halting from inside stage 2
  is less predictable than letting stage 2 fail. Under `S6_BEHAVIOUR_IF_STAGE2_FAILS=2`
  (agent-shell-base/Dockerfile:55), a failed cont-init stops the container before any
  services.d longrun starts, so no postmaster ever runs. The container's exit code on
  this path is s6-overlay's stage-2 failure code, not one we choose. It cannot be
  known offline, so the smoke step prints it (`docker inspect`) and asserts it is
  non-zero (phase-1 review p1-r1); the PR body records the value the branch build saw. A pod netns outlives
  container restarts, so a stray holder trips this on every restart: kubelet's
  CrashLoopBackOff, capped at 5 minutes, is the bounded retry.
- **Identity check (R2):** `services.d/hindsight-api/run` keeps its `pg_isready` wait.
  It then reads the expected id with `LC_ALL=C pg_controldata -D "$PGDATA"` (the
  "Database system identifier" line; the locale pin keeps the label stable) and the
  served id with
  `PGCONNECT_TIMEOUT=5 psql -X -w -h 127.0.0.1 -p 5433 -U hindsight -d postgres -Atc 'select system_identifier from pg_control_system()'`:
  `-w` never prompts for a password, `-X` skips any psqlrc, and the timeout bounds a
  stalled server. Both binaries come from the baked `hindsight-pg` env, where `hindsight`
  is the bootstrap superuser with trust auth (30-hindsight-initdb:19-23). The
  "unreadable" branch is a non-zero exit or empty output from either command. A mismatch
  or an unreadable id calls `halt-container 1 "<reason naming both ids>"` and then
  `exit 1`, so hindsight-api is never exec'd. The pre-flight closes the boot window; this
  check covers a foreign postgres that appears later, for example while ours is backing
  off. The system identifier is chosen over `data_directory` because it identifies the
  cluster, not a path a second container could also mount.
- **Give-up halts (R3):** in `services.d/postgres/finish`, the branch that today
  `exit 125`s (finish:49-55) calls `halt-container 125 "<message>"` and then `exit 125`.
  The backoff state machine and its fast-failure policy do not change. The message
  changes from "the service stays DOWN" to say the container is being stopped.
- **R4** follows from R2 and R3: with a foreign postgres the API is never exec'd, and
  after a give-up the container exits. It is verified by the identity unit tests and the
  give-up smoke step (see Verification), not on frank. The README's hindsight section
  states this behaviour.
- **Version strings (R7):** `README.md:29`, the `Dockerfile:15` comment and the
  `hindsight-api/run:2` header say 0.8.5. A pytest guard
  (`scripts/tests/test_hindsight_version_strings.py`) parses `ARG HINDSIGHT_API_VERSION`
  and, in each of those three files, finds every match of
  `hindsight-api-slim(\[[^]]*\])?(==|\s+)(\d+\.\d+\.\d+)` (extras optional, separator `==`
  or whitespace). It asserts each match equals the ARG and that **each file has at least
  one match**, so a reworded line cannot pass by matching nothing. The Dockerfile's
  `==${HINDSIGHT_API_VERSION}` pin is not a literal and does not match.

**Tests.** Unit tests (pytest, under `scripts/tests/`, run for real with bash and
stubbed binaries on PATH, the same harness style as `test_hindsight_pg_backoff.py`):
- the pre-flight with a listener (exits 1, names the port) and without one (exits 0);
- api-run with a matching id (execs the hindsight-api stub), a mismatched id, a psql
  failure and an empty pg_controldata (each calls the halt stub with 1 and never execs);
- finish at the give-up limit, which calls the halt stub with 125 and exits 125, while
  the existing backoff tests keep passing;
- the halt helper itself, against a temp `S6_RESULTS_DIR` and a stub `S6_HALT`;
- the chmod assertion extended to every new script.

CI smoke jobs in `.github/workflows/build.yaml` (`smoke-test-hermes-agent-shell-hindsight`):
- **Pre-flight.** The existing #160 collision step (build.yaml:996-1042) becomes: 5433
  is held by the pg-holder listener, and the container (not `--rm`, so its logs and state
  survive) exits within 60s. The step prints `docker inspect -f '{{.State.ExitCode}}'`
  and asserts it is non-zero, the log names the pre-flight, and the log has zero
  `could not create any TCP/IP sockets` lines.
- **Give-up.** A new step first initialises a PGDATA on a host dir with a short first
  `docker run` of the image under the K8s-equivalent flags. It waits for `pg_isready`,
  then `docker stop`s it. As UID 1000 it appends an invalid GUC
  (`shared_buffers = 'bogus'`) to `pgdata/postgresql.auto.conf`, then starts a second
  container (not `--rm`) on that dir. It asserts bounded fast failures (≤ 6
  `FAILED to start`/backoff lines), then a container exit with
  `docker inspect` ExitCode **125**, within 150s.

### agent-session fence (R5–R6)

`_send_locked` reads `end_session = req.get("end_session") is not False`
(agent-session:576), so only an explicit JSON `false` disables the fence. A missing key,
`null`, or a non-boolean such as the string `"false"` keeps it on, which errs toward the
safe side, as the old "only `true` enables" rule did for the opposite default. The
`/v1`-only defaulting in `serve()` (agent-session:753-755) is removed, since the default
now lives in one place. The CLI goes through the same `send()` (:783-786). `fresh` is
unchanged ("only `true` enables").

**Conversation cost.** For `claude` the fenced session resumes on the next send
(`launch_command` uses `--resume` for an existing transcript, agent-session:174-187).
**Other agent profiles** have no resume, so under the new default each turn starts a
fresh conversation. A non-claude caller that needs continuity must send
`end_session: false`. The README states this, and R5's "the conversation still resumes"
holds for claude only. frank's consumers (alert-agent, n8n) all drive `claude`.
Proactive `/compact` is skipped for a fenced turn (agent-session:672); claude's own
near-limit auto-compact remains.

**Tests** (multi-agent-shell/tests/test_agent_session.py). Each existing test the flip
changes is listed:
- `test_v1_ends_session_by_default_legacy_path_does_not` (:864) becomes
  `test_every_path_ends_session_by_default`, covering legacy, `/v1` and the CLI;
- `test_cli_send_keeps_session_by_default` (:858) is inverted into
  `test_cli_send_ends_session_by_default`, plus an explicit-`false` variant that keeps it;
- `test_flags_require_json_true` (:915) is split: its `fresh` half is unchanged, and its
  `end_session` half becomes `test_end_session_only_false_disables` (string `"false"`
  keeps the fence, JSON `false` keeps the session);
- `test_live_existing_session_is_reused` (:388), `test_slow_live_existing_session_reused`
  (:405), `test_absent_session_still_creates` (:421) and
  `test_compacts_when_context_over_threshold` (:587) pin warm reuse or compaction, so
  they send `end_session: False` explicitly and keep their assertions;
- `test_v1_explicit_null_keeps_fence_on` (:925) is kept, and gains a legacy-path twin.

**README** (multi-agent-shell/README.md): rewrite the legacy-alias line (:239-240, "differs
only in the end_session default", which is no longer true), the `end_session` paragraph
and the `/session/send` → `/v1` migration note (:257-270), and the JSON-boolean rule
(:272-273: for `end_session`, only an explicit `false` disables). Add the non-claude cost.

### Housekeeping (R8)

The plan text is already reconciled for phase 6: 06.yaml:42-52 ticks its steps "done at
merge of #155". What remains is on the run cursor
(`docs/superpowers/runs/2026-10-11-feat-upstream-version-sweep.yaml`: cursor
`implement`, `phase/6/implement-phase: pending`, `phase/7: manual`, then `journal-check`
and `deliver`) and phase 7's text. The work:
- tick P7.T1.S2, with the note "omnictl left at v0.45.1: the Omni server version was not
  established";
- file an agent-images issue for discovering the live Omni server version and pinning
  `omnictl` to it in `infra-shell/Dockerfile:30` and `upgrade-session/Dockerfile:53`
  (phase 7's text names `kali/Dockerfile`, which no longer exists);
- close the cursor. Reshape it onto the current step list (it predates `lens-review`) or
  adopt with `--supersede`, then walk it to done or archive it, whichever `fr` accepts for
  a merged plan, recording phase 6 as done at #155's merge;
- move the plan to `docs/superpowers/implemented/plans/`, matching the existing layout.

The `2026-10-31--life--upgrade-session-image` plan, which `fr migrate` lists as
cursor-less, is not part of #170 and is left alone.

## Not in scope

- The frank-side `fresh` adoption: derio-net/frank#990.
- Re-pinning frank's hindsight sidecar to the new SHA. That is the bump PR the merge's
  `dispatch-frank` opens.
- Confirming #152's root cause. The fence mitigates it whatever the cause.

## Verification

- hindsight-port-preflight: none — the pre-flight is proven by the pytest unit tests and by the dispatched branch build's hindsight smoke job (5433 held → non-zero exit, no postmaster); the repo has `ci none`, no `.fr/candidate-install`, and build.yaml never runs on PRs.
- hindsight-identity-check: none — the pytest unit tests (match / mismatch / unreadable id) prove it; a foreign postgres appearing after the pre-flight cannot be staged reliably in the smoke job.
- hindsight-giveup-halts: none — proven by the pytest finish test and the dispatched branch build's give-up smoke step (bad postgresql.auto.conf → bounded attempts → container ExitCode 125); together with the identity unit tests this is also R4's evidence.
- agent-session-fence-default: none — proven by the multi-agent-shell pytest suite (`tests/test_agent_session.py`), which drives the real handler over every path.
- hindsight-version-strings: none — proven by the pytest version-string guard.
gate: tester
gate: hindsight-port-preflight=tester
gate: hindsight-identity-check=tester

## Test Plan

- [ ] post-merge — operator-driven, BEFORE merging frank's bump PR: inside the hermes-agent-shell pod, check whether anything other than the hindsight sidecar's own postgres holds 127.0.0.1:5433 (the stray ssh-sidecar postgres frank's deployment comment records since 2026-08-19). If one does, `pg_dump` whatever hindsight wrote to it, restore that into the sidecar's PGDATA, and stop the stray server. Otherwise the new pre-flight crash-loops the sidecar, by design.
- [ ] post-merge — operator-driven: after frank's agent-images bump PR pins the hermes-agent-shell-hindsight SHA from this merge, the `hindsight` sidecar of the hermes-agent-shell pod reaches Ready, `curl -sf http://127.0.0.1:8888/health` inside it returns `healthy`, and its logs show the port pre-flight and identity check passing (no `halt-container`).
- [ ] post-merge — operator-driven: after the bump reaches the alert-agent / n8n agent-session consumers, one alert-agent chat turn and one n8n-driven turn still complete, and the second turn in the same session remembers the first (the fence resumes the conversation).

## Implementation Plans

| Plan | Repo | File | Depends on |
|------|------|------|------------|
| 2026-11-14-hindsight-giveup-signal | `derio-net/agent-images` | `2026-11-14-hindsight-giveup-signal` | — |
