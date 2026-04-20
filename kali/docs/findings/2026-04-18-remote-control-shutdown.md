# Remote-Control Shutdown — Findings

Phase 0 spike for the `persistent-agent-reliability` plan. Goal: determine
whether the `claude` CLI offers a clean way to disconnect a remote-control
session so the persistent agent stops accumulating phantom sessions in
claude.ai.

Investigation environment: `claude` 2.1.114 inside the agent pod
(`/home/claude/.local/share/claude/versions/2.1.114`, 236 MB statically
linked binary).

## CLI surface

`claude --help` and `claude remote-control --help` were inspected. Relevant
remote-control flags exist on the `claude` top level and on the subcommand:

```
--remote-control-session-name-prefix <prefix>
    Prefix for auto-generated Remote Control session names
    (default: hostname; env: CLAUDE_REMOTE_CONTROL_SESSION_NAME_PREFIX)
```

`claude remote-control --help` documents only `--name`, `--spawn`,
`--capacity`, `--permission-mode`, `--debug-file`, `--verbose`, and
`--[no-]create-session-in-dir`. **No subcommand for `list`, `close`,
`disconnect`, `stop`, or `rm` exists**:

```
$ claude remote-control list
Error: Unknown argument: list
$ claude remote-control close
Error: Unknown argument: close
```

`claude auth` only exposes `login`, `logout`, `status` — nothing
session-aware.

In short: **no public CLI affordance for remotely closing a specific
remote-control session by name or id.**

## State dir

`~/.claude/` contains the expected layout. The two interesting
subdirectories:

- `~/.claude/sessions/<pid>.json` — one entry per *currently running* CLI
  process. Schema:
  `{pid, sessionId (uuid), cwd, startedAt, version, kind, entrypoint}`.
  This is purely an in-process registry — restarts of the agent leave no
  stale entries here.
- `~/.claude/session-env/<uuid>/` — **1 123 empty directories** on the
  inspected pod. These are per-session scratch dirs that the CLI creates
  when a session starts but never removes on exit. They do not contain the
  remote `environment_id` returned by the bridge API; they are local
  bookkeeping only.

The bridge environment id is *not* persisted to a stable file the operator
can grep for. The CLI writes a `bridge-pointer.json` under
`~/.claude/projects/<encoded-cwd>/bridge-pointer.json` while a bridge is
active (encoder logic: `kD$.join(s8(), "projects", IJ(cwd))`). On the
inspected pod no such file exists — the agent's bridge sessions had
already exited by the time we looked. The pointer is removed by the CLI's
own graceful-shutdown handler (`clearBridgePointer(dir)`), so it is
present only while the bridge process is alive.

The 1 123 empty `session-env/` dirs are a separate accumulation bug
(per-session scratch space that is never cleaned up). They are local
disk noise but not the cause of the phantom claude.ai sessions.

## Server endpoint

A clean disconnect endpoint **does exist**, even though it is not surfaced
on the CLI. Strings extracted from the binary include the bridge HTTP
client:

```
[bridge:api] POST   /v1/environments/bridge        (registerBridgeEnvironment)
[bridge:api] DELETE /v1/environments/bridge/<env_id>   (deregisterEnvironment)
[bridge:api] POST   /v1/sessions/<id>/archive          (archiveSession)
[bridge:api] POST   /v1/environments/<env>/work/<id>/stop  (stopWork)
```

The CLI's own shutdown path uses these. Decompiled inline from the binary
(string-extracted, formatting cleaned up):

```js
[bridge:shutdown] Shutting down ${D.size} active session(s)
[bridge:shutdown] Sending SIGTERM to sessionId=${e}
[bridge:shutdown] Force-killing stuck sessionId=${e}
[bridge:shutdown] Cleaning up ${e.length} worktree(s)
…
await K.deregisterEnvironment($)
[bridge:shutdown] Environment deregistered, bridge offline
await clearBridgePointer(H.dir)
```

The handler is wired to `SIGTERM` at top level:

```js
process.on("SIGTERM", () => {
    A8("info","shutdown_signal",{signal:"SIGTERM"});
    w7(143);
});
```

Where `w7(143)` is the graceful exit path that drains `bridge:shutdown`
above — i.e. **a SIGTERM delivered to the `claude remote-control` process
itself triggers `DELETE /v1/environments/bridge/<env_id>` against the
Anthropic API and removes the local pointer.**

Auth headers used by `deregisterEnvironment` are the same OAuth bearer
already cached in `~/.claude/.credentials.json`, plus
`x-organization-uuid`. There is no separate setup the agent needs.

Bottom line: the *capability* is there. The *bug* is that the agent never
gets to invoke it — the supervisor wrapper hides the right PID and the pod
shutdown path doesn't deliver SIGTERM to claude.

## Signal behavior

Live SIGTERM/SIGINT testing was deferred — running a real
`claude remote-control` from the spike pod would create a real environment
in claude.ai (the user's account), and if the signal handler reasoning
below is wrong the test itself would leave a phantom. The static evidence
above is sufficient to decide Phase 1's direction; Phase 1 verifies
empirically when implementing `shutdown.sh`.

The relevant structural problem is in the existing supervisor.
`scripts/session-manager.sh` starts each bridge as:

```bash
nohup bash -c "echo y | claude remote-control --name '$SESSION_NAME'" \
  >> "...session-${SESSION_NAME}.log" 2>&1 &
echo $! > "$PIDFILE"
```

The PID written to `$PIDFILE` is the wrapper `bash -c`, not `claude`.
On `kill -TERM "$(cat $PIDFILE)"`:

- `bash` receives SIGTERM. It does not forward signals to children of a
  pipeline by default. `bash -c '<pipeline>'` exits, the pipeline is left
  to finish or get reaped, and `claude`'s own SIGTERM handler is
  **not** invoked by our kill.
- Even if claude eventually exits, it exits because its stdin/stdout
  closed, not because of SIGTERM — that path goes through process exit
  cleanup, not the documented `bridge:shutdown` handler. The remote
  bridge is not deregistered.
- On pod termination, Kubernetes sends SIGTERM to PID 1 (here:
  vibe-kanban or supercronic depending on context); orphaned `claude`
  processes get SIGKILL after the grace period — also no clean shutdown.

This matches the symptom: phantoms accumulate one-per-restart in
claude.ai.

The fix has two parts:

1. **Make the tracked PID == claude's PID.** Replace the wrapper with
   `exec`, e.g.
   `nohup bash -c "exec claude remote-control --name '$SESSION_NAME' < <(echo y)" …`
   so `bash` is replaced in-place by `claude`. Now `kill -TERM
   "$(cat $PIDFILE)"` reaches the claude process directly and its
   internal SIGTERM handler runs `bridge:shutdown` → DELETE
   `/v1/environments/bridge/<env_id>`.
2. **Add a pod-level shutdown hook** (`scripts/shutdown.sh`) that loops
   over `$PIDDIR/*.pid` and sends SIGTERM, then waits up to ~30 s
   (bridge:shutdown's `loop_grace_ms` default) before SIGKILL. Wire it as
   a Kubernetes `preStop` hook on the agent deployment in
   `derio-net/frank` so the pod actually gets a chance to deregister
   before SIGKILL.

The Frank deployment change is filed as a separate Issue against
`derio-net/frank`, per the plan's architecture note — not part of this
plan's PR chain.

## Decision for Phase 1

**Chosen: A (close API available).**

Reason: The CLI bundles a working bridge-deregister code path
(`DELETE /v1/environments/bridge/<env_id>` invoked from
`[bridge:shutdown]`) and wires it to `SIGTERM`. We do not need to
reverse-engineer or reimplement that endpoint. We need only deliver
SIGTERM to the right PID and give the process time to drain. Concretely
Phase 1 should:

- Change `session-manager.sh` to launch claude via `exec` so `$PIDFILE`
  records claude's PID (not bash's).
- Add `scripts/shutdown.sh` that iterates the PID dir, sends SIGTERM,
  waits ≤30 s per process, then SIGKILL as fallback.
- File a separate Issue against `derio-net/frank` to wire `shutdown.sh`
  as a `preStop` hook with a `terminationGracePeriodSeconds` ≥ 35.
- Independent cleanup for the 1 123 stale `~/.claude/session-env/<uuid>/`
  dirs (cron job that prunes empty ones older than N hours) belongs in
  the housekeeping batch — it is unrelated to phantoms in claude.ai.
- Verify empirically during Phase 1 implementation: start a bridge,
  capture the claude PID directly, send SIGTERM, confirm the
  `claude.ai/code` UI shows the session disappear within 30 s and that
  `bridge-pointer.json` is removed.
