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
The fence keeps the conversation: `_end_session` kills the tmux session, the claude
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
R5. The post-turn fence ends the harness session by default on every send path, legacy `/session/send`, `/v1/session/send` and the `agent-session send` CLI; only an explicit JSON `false` for `end_session` keeps the session, and the conversation still resumes on the next send.
R6. The README documents the new fence default, its cost (cold start per turn, no proactive compaction) and the `end_session: false` opt-out.
R7. No `0.8.4` hindsight-api version string remains, and a test fails if a hindsight-api version mentioned in the image's README, Dockerfile comment or run script disagrees with `ARG HINDSIGHT_API_VERSION`.
R8. The version-sweep plan is reconciled: phase 6 is recorded as done at #155's merge, P7.T1.S2 is ticked ("omnictl left at v0.45.1: the Omni server version was not established"), the real omnictl-to-server discovery is filed as an agent-images issue, and the plan and its run cursor are closed out.

## Design

### Hindsight (R1–R4, R7)

A small shared helper, `/usr/local/lib/hindsight/halt-container <code> <reason>`, prints
the reason to stderr, writes `<code>` to `/run/s6-linux-init-container-results/exitcode`,
and runs `/run/s6/basedir/bin/halt`. That is s6-overlay v3's documented way for a service
to stop the container with a chosen exit code, and it works rootless because s6 owns `/run`
as UID 1000 under the K8s securityContext. Every path below uses it, so there is one
place to get halting right.

- **Port pre-flight (R1):** a new cont-init `35-hindsight-port-preflight` (after
  `30-hindsight-initdb`) probes `127.0.0.1:5433` with bash's `/dev/tcp`. If the port
  accepts a connection, it prints the error and exits 1. The base image sets
  `S6_BEHAVIOUR_IF_STAGE2_FAILS=2`, so a failed cont-init stops the container, with no
  postmaster ever started. A pod netns outlives container restarts, so a stray holder
  trips this on every restart: kubelet's CrashLoopBackOff, capped at 5 minutes, is the
  bounded retry.
- **Identity check (R2):** `services.d/hindsight-api/run` keeps its `pg_isready` wait,
  then reads the expected id with `pg_controldata -D "$PGDATA"` ("Database system
  identifier") and the served id with
  `psql -h 127.0.0.1 -p 5433 -U hindsight -d postgres -Atc 'select system_identifier from pg_control_system()'`.
  Both binaries come from the baked `hindsight-pg` env. If they differ, or either is
  empty, it calls `halt-container 1 "<reason naming both ids>"` and never execs
  hindsight-api. The pre-flight closes the boot window; this check covers a foreign
  postgres that appears later, for example while ours is backing off. The system
  identifier is chosen over `data_directory` because it identifies the cluster, not a
  path a second container could also mount.
- **Give-up halts (R3):** in `services.d/postgres/finish`, the branch that today
  `exit 125`s calls `halt-container 125 "<the existing message>"` first. The backoff
  state machine and its fast-failure policy do not change. The message changes from
  "the service stays DOWN" to say the container is being stopped.
- **R4** follows from R2 and R3: with a foreign postgres the API is never exec'd, and
  after a give-up the container exits. The README states it, and the Test Plan below
  exercises it on frank.
- **Version strings (R7):** `README.md:29`, the `Dockerfile:15` comment and the
  `hindsight-api/run:2` header say 0.8.5. A pytest guard
  (`scripts/tests/test_hindsight_version_strings.py`) parses `ARG HINDSIGHT_API_VERSION`
  and asserts every `hindsight-api-slim[...] X.Y.Z` / `==X.Y.Z` mention in those three
  files matches it.

**Tests.** Unit tests (pytest, under `scripts/tests/`, run for real with bash and
stubbed binaries, the same harness style as `test_hindsight_pg_backoff.py`): pre-flight
with a listener and without; api-run with a matching id (execs the stub), a mismatched
id, and an unreadable id (halts with the right code, never execs); finish at the give-up
limit calls the halt helper with 125. Each new script must be `chmod +x`'d in the
Dockerfile, and a test asserts that. CI smoke jobs in `.github/workflows/build.yaml`
(`smoke-test-hermes-agent-shell-hindsight`): the existing #160 collision step becomes
"5433 held → container exits non-zero within N s, with zero `could not create any TCP/IP
sockets` attempts" (the pre-flight); a new give-up step seeds a PGDATA whose
`postgresql.auto.conf` carries an invalid setting so postgres fails fast every time, then
asserts bounded attempts followed by a non-zero container exit.

### agent-session fence (R5–R6)

`_send_locked` reads `end_session = req.get("end_session") is not False`, so only an
explicit JSON `false` disables the fence. A missing key, `null`, or a non-boolean such as
the string `"false"` keeps it on, which errs toward the safe side, as the old "only `true`
enables" rule did for the opposite default. The `/v1`-only defaulting in `serve()` is
removed, since the default now lives in one place. The CLI goes through the same
`send()`. `fresh` is unchanged. Tests:
`test_v1_ends_session_by_default_legacy_path_does_not` becomes
`test_every_path_ends_session_by_default`, covering legacy, `/v1` and the CLI. Explicit
`false` keeps the session on each path, and a non-boolean `"false"` keeps the fence. The
existing null-keeps-fence test is kept. README: the `end_session` paragraph and the
migration note for `/session/send` → `/v1` (which today tells callers to send
`end_session: false`) are rewritten for the single default.

### Housekeeping (R8)

Tick the version-sweep plan's phase 6 steps (if any are still unticked) and P7.T1.S2,
noting #155's merge. File an agent-images issue for discovering the live Omni server
version and pinning `omnictl` to it in `infra-shell/Dockerfile` and
`upgrade-session/Dockerfile`; phase 7's text names `kali/Dockerfile`, which no longer
exists. Close the cursor (reshape or adopt with `--supersede`, then walk it to done or
archive it, whichever `fr` accepts for a merged plan) and archive the plan under
`docs/superpowers/implemented/`. The `2026-10-31--life--upgrade-session-image` plan,
which `fr migrate` lists as cursor-less, is not part of #170 and is left alone.

## Not in scope

- The frank-side `fresh` adoption: derio-net/frank#990.
- Re-pinning frank's hindsight sidecar to the new SHA. That is the bump PR the merge's
  `dispatch-frank` opens.
- Confirming #152's root cause. The fence mitigates it whatever the cause.

## Verification

- hindsight-port-preflight: none — the pre-flight is proven by the pytest unit tests and by the dispatched branch build's hindsight smoke job (5433 held → non-zero exit, no postmaster); the repo has `ci none`, no `.fr/candidate-install`, and build.yaml never runs on PRs.
- hindsight-identity-check: none — the pytest unit tests (match / mismatch / unreadable id) prove it; a foreign postgres appearing after the pre-flight cannot be staged reliably in the smoke job.
- hindsight-giveup-halts: none — proven by the pytest finish test and the dispatched branch build's give-up smoke step (bad postgresql.auto.conf → bounded attempts → non-zero exit).
- agent-session-fence-default: none — proven by the multi-agent-shell pytest suite (`tests/test_agent_session.py`), which drives the real handler over every path.
- hindsight-version-strings: none — proven by the pytest version-string guard.
gate: tester

## Test Plan

- [ ] post-merge — operator-driven: after frank's agent-images bump PR pins the hermes-agent-shell-hindsight SHA from this merge, the `hindsight` sidecar of the hermes-agent-shell pod reaches Ready, `curl -sf http://127.0.0.1:8888/health` inside it returns `healthy`, and its logs show the port pre-flight and identity check passing (no `halt-container`).
- [ ] post-merge — operator-driven: after the bump reaches the alert-agent / n8n agent-session consumers, one alert-agent chat turn and one n8n-driven turn still complete, and the second turn in the same session remembers the first (the fence resumes the conversation).
