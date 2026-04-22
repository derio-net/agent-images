# Silent-Reconnect Phantom Reaper — Design

**Date:** 2026-04-22
**Status:** Approved

## Problem

The 48h Phase 3 soak of `2026-04-18-persistent-agent-reliability` left 17
phantom `willikins` remote-control environments in claude.ai. Stratification:

- ~6 from `vk-local` OOMKills (SIGKILL bypasses `preStop` → no SIGTERM to
  claude → no `bridge:shutdown`).
- ~11 from `session-manager.sh` relaunching `willikins` after the prior
  claude process died silently (vk-local tunnel failure severing
  stdin `<(echo y)`, SIGPIPE cascade, or similar), again skipping SIGTERM.

Mechanism is identical in both groups: **claude exits without running its
own `[bridge:shutdown]` handler, so `DELETE /v1/environments/bridge/<env_id>`
is never called and the server-side env persists as a phantom.** The Phase 2
graceful-shutdown path only helps for SIGTERM-driven drains, which is a
minority of real-world deaths.

## Solution

Add a client-driven orphan-env reaper that runs inline in
`session-manager.sh` on every 5-minute tick, discovers envs whose owning
claude process is gone, and calls the bridge-deregister HTTP endpoint
directly — closing the phantom leak regardless of the cause of claude's
death.

The reaper anchors on `~/.claude/projects/<cwd>/bridge-pointer.json`, the
file the CLI writes while a bridge is alive and removes in its own graceful
shutdown. An unclean exit should leave the pointer on disk — that is our
"orphan receipt." Phase 0 verifies this assumption live; if it fails, the
plan switches to a Python supervisor wrapper that tracks env_id in a file
we own.

## Design

### Phase 0 — Recon spike

Live-verify the three load-bearing unknowns on the pod:

- **Pointer survival under SIGKILL.** Start a throwaway
  `claude remote-control --name spike-reaper` bridge, confirm
  `~/.claude/projects/<cwd>/bridge-pointer.json` exists while it is running,
  `kill -9` the process, confirm the pointer remains with `env_id`
  extractable.
- **Pointer PID field.** Parse the JSON. Does it contain the originating
  PID? If yes, the reaper's liveness test is "PID exists and is claude." If
  no, the test is "no live claude in this pod has this env registered" —
  covered by the fact that a newly-spawned claude writes a new pointer path.
- **Credentials and DELETE signature.** Locate the bearer token
  (`~/.claude/.credentials.json` per findings doc) and the
  `x-organization-uuid` header value (likely in
  `~/.claude/config.json` / state files — Phase 0 pins the path). Compose a
  working `curl -X DELETE https://api.anthropic.com/v1/environments/bridge/<env_id>`
  against the spike env and verify the response and that the env disappears
  from claude.ai.
- **TTL note (observational).** If convenient, record whether any orphan
  env persists or disappears on its own over a few hours — informs whether
  the reaper is strictly necessary or belt-and-suspenders. Not gating.

**Output:** `kali/docs/findings/2026-04-22-orphan-env-reaper.md` with a
Decision section:

- **A (pointer-based).** Pointer survives SIGKILL. Phase 1 Branch A.
- **B (wrapper-based).** Pointer does not survive SIGKILL. Phase 1 Branch B.

Phase 1 Task 1 Step 1 reads this file and branches accordingly.

### Phase 1 Branch A — pointer-based reaper

**New: `kali/scripts/reap-orphan-envs.sh`** (bash + jq + curl)

- Iterates `~/.claude/projects/*/bridge-pointer.json` via shell glob.
- For each pointer: `jq` out `env_id` and (if present) `pid`.
- Liveness test: if pid field present and `kill -0 <pid>` succeeds, skip.
  Otherwise treat pointer as orphaned.
- Auth: read bearer from `~/.claude/.credentials.json` and org UUID from
  the path pinned by Phase 0. Build headers.
- `curl -fsS -X DELETE -H 'Authorization: Bearer ...' -H 'x-organization-uuid: ...' \
   https://api.anthropic.com/v1/environments/bridge/<env_id>`.
- **Success classification:** 2xx → remove pointer. 404 → treat as
  already-gone, remove pointer. 401/403 → log `[reap][error]`, leave
  pointer for next tick, increment an error counter. 5xx → log
  `[reap][warn]`, leave for next tick.
- **Auth-failure backoff.** A persistent-error state file
  (`~/.willikins-agent/reap-auth-error.state`) records consecutive auth
  failures. When that count exceeds N (default 3), reaper skips its own run
  for 1 hour to prevent log spam. Reset on next success.
- Logs to `~/.willikins-agent/reap-orphan-envs.log` with structured lines:
  `[YYYY-MM-DD HH:MM:SS UTC] [reap] <event> <env_id=...> <status=...>`.

**Modify: `kali/scripts/session-manager.sh`**

- Call reaper as the first action each tick, before the `SHUTDOWN_MARKER`
  check's spawn loop — gated by a `REAP_ORPHAN_ENVS=${REAP_ORPHAN_ENVS:-1}`
  switch so we can disable via env during debugging.
- Reaper invocation is non-fatal: `|| log "[warn] reaper nonzero exit"`.

**New: `kali/tests/test_reap_orphan_envs.sh`** (bash harness)

- Fixture: tmp `HOME` with `~/.claude/projects/a/bridge-pointer.json` (dead
  PID), `~/.claude/projects/b/bridge-pointer.json` (live PID bound to the
  test harness's own PID), fake credentials files.
- Stub curl by prepending a shim dir to `PATH` that records arguments to a
  log file and returns a canned response code.
- Assertions: DELETE called once (for `a`, not `b`), pointer `a` removed,
  pointer `b` untouched, log file contains the expected structured line.
- Stub scenarios also cover 404, 401, and 5xx response codes.

### Phase 1 Branch B — supervisor wrapper

Triggered only if Phase 0 records Decision **B**.

**New: `kali/scripts/wrap-claude.py`** (~60 LOC, Python 3.11)

- `argv[1:]` is the claude command to run (e.g.
  `["remote-control", "--name", "willikins"]`).
- Spawns claude via `subprocess.Popen` with `stderr=PIPE`, line-buffered.
- Tails stderr, writes unchanged to real stderr, simultaneously greps for
  the env-registration pattern captured in Phase 0 (shape to be confirmed
  there; e.g. `registered environment env_XXXX`). On match, writes
  `~/.willikins-agent/envs/<session>.json` with
  `{"env_id": "...", "pid": <claude_pid>, "started_at": "<iso8601>"}`.
- Forwards SIGTERM/SIGINT to the child, `wait()`s on it, exits with the
  child's exit code.
- On exit code 0 (graceful shutdown), removes
  `~/.willikins-agent/envs/<session>.json`.
- On exit code != 0 (crash), leaves the file for the reaper to catch.

**Modify: `kali/scripts/session-manager.sh`**

- Change spawn line from
  `exec claude remote-control --name '$SESSION_NAME' < <(echo y)` to
  `exec python3 -u /opt/scripts/wrap-claude.py remote-control --name '$SESSION_NAME' < <(echo y)`.
  The wrapper's PID becomes the tracked PID — and because wrap-claude.py
  uses `Popen` then waits, its own PID dying still implies the claude child
  is dead (wrapper either forwarded SIGTERM and waited, or got SIGKILLed
  alongside claude).

**Modify: reaper**

- Scan `~/.willikins-agent/envs/*.json` instead of the CLI pointer files.
- Same liveness test, same DELETE logic, same error handling.

**New: `kali/tests/test_wrap_claude.py`** (pytest)

- Fake-claude helper subprocess that prints the registration line then
  sleeps until signaled. Verify the envs file appears with correct env_id,
  that SIGTERM forwarded to the child causes the file to be removed, and
  that SIGKILL (skipping the wrapper's shutdown path) leaves the file.

### Phase 2 — 48h soak

- **Deploy:** rebuild `secure-agent-kali` image, bump the Frank deployment's
  image tag (no Frank-side Deployment changes otherwise — the reaper runs
  inside the existing supercronic/session-manager flow).
- **Baseline capture:** phantom count in claude.ai UI, `reap-orphan-envs.log`
  empty-file existence, observed env-registration log pattern from
  `session-willikins.log`.
- **Checkpoints at T+8h, T+24h, T+48h** — each records:
  - Number of session-manager "stale PID → restart" events in the window.
  - Number of reaper DELETE invocations (by response code).
  - New phantom count in claude.ai.
  - Restart-cause stratification (OOMKill vs stdin-closed vs other) via
    `kubectl describe`.

**Acceptance:**
- Net phantom growth over the 48h window ≤ 1 (ideally 0).
- Every stale-PID detection corresponds to a reaper DELETE attempt.
- DELETE responses ≥90% 2xx, remainder 404. Any 401/403/5xx investigated.

**Follow-up triggers:**
- Phantoms still accumulating despite DELETEs succeeding → log-scan to find
  which unclean-death path the reaper misses (e.g., pointer path is
  per-cwd and a session moved cwds mid-life).
- 401/403 on DELETE → creds-handling fix (credentials file format drifted).
- 5xx on DELETE → rate limiting or Anthropic-side issue; consider backoff
  policy revision.
- TTL discovered to be short (<24h) in Phase 0 → document that the reaper
  is belt-and-suspenders rather than strict cleanup; reprioritize this
  plan in the roadmap.

## Scope

- **In scope:** Phase 0 recon, reaper helper (bash Branch A or Python
  wrapper Branch B), session-manager integration, tests, 48h soak on the
  pod.
- **Out of scope:**
  - `derio-net/frank` deployment-level changes. No preStop change, no
    `terminationGracePeriodSeconds` bump — the reaper runs in the already-
    deployed container.
  - Reducing OOMKill frequency (owned by
    `2026-04-22-vk-local-memory-profile.md`).
  - Broadening vk-bridge discovery warn-pattern coverage (owned by
    `2026-04-22-vk-bridge-warn-patterns.md`).
  - Upstream feature request to Anthropic for a CLI
    `claude remote-control close`. Only filed if Phase 0 chooses a
    degraded outcome (no env_id recoverable by either Branch A or B).
  - `WILLIKINS_REPOS` multi-session expansion (same non-goal as original
    plan).

## Risks

| Risk | Mitigation |
|---|---|
| Pointer PID collides with a reused PID in the new pod, reaper thinks orphan is live. | Acceptable — pointer stays until next tick's liveness test flips; at worst a single phantom persists ≤5 minutes longer. |
| DELETE 401/403 loops spam the log. | Auth-error backoff: N consecutive auth failures → reaper sleeps 1 hour before retrying. |
| Phase 0 finds neither Branch A nor Branch B feasible (no env_id recoverable anywhere). | Abort plan at end of Phase 0, findings doc documents the upstream feature request path. Only the OOMKill-frequency fix from Plan 3 applies; phantoms continue at reduced rate. |
| Branch B wrapper swallows claude's exit status or breaks supercronic's visibility into claude liveness. | Wrapper forwards child's exit code verbatim via `sys.exit(child.returncode)` and `wait()`s on the child. Tests verify exit-code passthrough and that SIGTERM received by the wrapper is forwarded to claude. |
| Reaper invocation adds latency to session-manager's 5-minute tick. | Reaper finishes in <1s in the steady state (empty glob) or <5s with a few DELETE calls; well within the 5-minute window. |

## Implementation Plans

| Plan | Repo | File | Status | Depends on |
|------|------|------|--------|------------|
| Silent-Reconnect Phantom Reaper Implementation Plan |  | `docs/superpowers/plans/2026-04-22-silent-reconnect-phantoms.md` | Not Started | — |
