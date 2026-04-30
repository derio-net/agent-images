# Orphan-Env Reaper — Findings

Recon spike for plan `2026-04-22-silent-reconnect-phantoms.md` (Phase 0).
Performed live on the running `secure-agent-pod` `kali` container against
claude `2.1.119 (Claude Code)` and `https://api.anthropic.com`.

## Pointer survival under SIGKILL

**Conclusion: claude does not write a `bridge-pointer.json` file at all.** The
plan's Branch A premise is invalid. (See [Decision for Phase 1](#decision-for-phase-1)
for the chosen branch.)

Empirical verification:

```
# Before any spike, find for existing pointer files in claude state:
$ kubectl exec ... -- find ~/.claude/projects -name bridge-pointer.json
(no output — none exist)

# Started a throwaway bridge in /tmp/spike-reaper, named spike-reaper-2026-04-22.
# Bridge connected and emitted env_id env_01MPTBz8CJR82vP2qXJKpUvt.

# Mid-run check for any spike-reaper file under ~/.claude:
$ find ~/.claude -path "*spike-reaper*" -type f
(no output)

# After SIGKILL of claude PID 172096:
$ pgrep -f "claude remote-control --name spike-reaper"
(empty — claude gone)
$ find ~/.claude/projects -path "*spike-reaper*" -name bridge-pointer.json
(no output)
$ find ~/.claude -maxdepth 6 -name "bridge-pointer*"
(no output)
```

claude `2.1.119` does not persist any `bridge-pointer.json` (or any file with a
similar name) under `~/.claude` for `claude remote-control` sessions.
`~/.claude/projects/<slug>/` exists for other reasons (history, TODOs) but
contains no env_id/PID record. Trust state and account state live in the
top-level `~/.claude.json` only, with no per-session bridge state.

## Pointer JSON shape

N/A — no pointer file exists.

What does exist that is useful:

- **`~/.willikins-agent/pids/<session>.pid`** — written by our own
  `kali/scripts/session-manager.sh` (e.g. `pids/willikins.pid` contains the
  claude process's PID). This is the only PID record. It is removed by
  session-manager when the next tick detects a stale PID.
- **`~/.willikins-agent/session-<session>.log`** — the session's stdout/stderr,
  appended forever (rotated by `rotate-logs.sh`). The env_id appears in lines of
  the form `Continue coding in the Claude app or
  https://claude.ai/code?environment=env_<id>` (regex `env_[A-Za-z0-9]+`).
  Multiple env_ids accumulate across restarts.

These two together are the closest analogue to the assumed pointer file. They
are written by `session-manager.sh`, not by claude.

## Organization UUID location

- **File:** `~/.claude.json`
- **JSON path:** `.oauthAccount.organizationUuid`
- **Example value (real, current):** `3925f552-0949-47e8-b19d-21a34a6d0546`

Sibling fields under `.oauthAccount`: `accountUuid`, `emailAddress`,
`organizationUuid`, `hasExtraUsageEnabled`, `billingType`,
`accountCreatedAt`, ... (subscription metadata).

The bearer is **not** at the same well-known top-level key the plan template
assumed. Actual location:

- **File:** `~/.claude/.credentials.json`
- **JSON path:** `.claudeAiOauth.accessToken`
- **Sibling fields:** `expiresAt`, `rateLimitTier`, `refreshToken`, `scopes`,
  `subscriptionType`.

Token prefix observed: `sk-ant-oat01-...`.

## DELETE signature

The plan template was missing the required `anthropic-beta` header. The
endpoint refuses without it (HTTP 404 `not_found_error` with a hint message).

Working invocation, verified end to end on `env_01MPTBz8CJR82vP2qXJKpUvt`:

```bash
BEARER=$(jq -r ".claudeAiOauth.accessToken" ~/.claude/.credentials.json)
ORG_UUID=$(python3 -c 'import json,os; \
  print(json.load(open(os.path.expanduser("~/.claude.json")))["oauthAccount"]["organizationUuid"])')

curl -sS -X DELETE \
  -H "Authorization: Bearer $BEARER" \
  -H "x-organization-uuid: $ORG_UUID" \
  -H "anthropic-beta: environments-2025-11-01" \
  "https://api.anthropic.com/v1/environments/bridge/$ENV_ID" \
  -w "\nHTTP %{http_code}\n"
```

Observed responses:

- First call: `HTTP 200`, body `{"id":"env_01MPTBz8CJR82vP2qXJKpUvt","type":"environment_deleted"}`.
- Idempotent retry: `HTTP 404`, body `{"type":"error","error":{"type":"not_found_error","message":"Environment env_01MPTBz8CJR82vP2qXJKpUvt not found."},...}`.
- Without `anthropic-beta` header: `HTTP 404`, body `{"type":"error","error":{"type":"not_found_error","message":"The environments API requires the \`environments-2025-11-01\` value in the \`anthropic-beta\` header."},...}`.

The 404-on-retry shape is friendly to a "treat 404 as success, drop pointer"
branch in the reaper — same outcome as a fresh successful delete.

### Side note: no LIST endpoint discovered

`GET /v1/environments/bridge` and `GET /v1/environments` both return HTTP 400
with `Unexpected value(s) \`environments-2025-11-01\` for the \`anthropic-beta\`
header.` That 400 says the beta value is wrong for those paths, not that those
paths can't enumerate. We did not probe alternative beta values, org-scoped
shapes (e.g. `/v1/organizations/<uuid>/environments`), or other plausible
prefixes. **For Phase 1 purposes, treat the reaper as the authoritative env_id
record** — discovering a usable LIST endpoint later would only let a future
version become stateless; it is not required to ship the reaper.

## TTL note (optional)

n/a — DELETE succeeded on first attempt.

## Decision for Phase 1

- **A (pointer-based reaper):** `bridge-pointer.json` survives SIGKILL and exposes env_id.
- **B (supervisor wrapper):** pointer does not survive SIGKILL.

**Chosen: B (supervisor wrapper).**

**Reason:** Branch A is structurally impossible — claude `2.1.119` does not
write a `bridge-pointer.json` (or any equivalent state file) under `~/.claude`
for `claude remote-control` sessions. Empirical verification at three points
(before spike, mid-run, post-SIGKILL) found zero matching files anywhere under
`~/.claude`. We also found no LIST endpoint with the headers we tried (see Side
note above). The only sources of env_id today are claude's own stdout/stderr
("Continue coding in the Claude app or
https://claude.ai/code?environment=env_<id>"), which `session-manager.sh`
already redirects into `~/.willikins-agent/session-<name>.log`. Therefore Phase
1 must own the env_id record itself: a thin Python supervisor (`wrap-claude.py`)
that scrapes the env_id line from claude's stderr, writes
`~/.willikins-agent/envs/<session>.json` containing `{env_id, pid, started_at}`,
and unlinks it on graceful exit. Under SIGKILL the file is left behind for the
reaper. The reaper enumerates `~/.willikins-agent/envs/*.json` (NOT
`~/.claude/projects/*/bridge-pointer.json`) and uses `kill -0 $pid` for liveness.

### Plan-structure consequences

- All Branch A tasks (Phase 1 Tasks 2–3 in the plan) are irrelevant; do not
  author `kali/tests/test_reap_orphan_envs.sh` against pointer files. The
  Branch B variant scanning `$WILLIKINS_AGENT_DIR/envs/*.json` is the only
  one that matches reality.
- Phase 1 Task 1's grep already routes execution to Branch B given the
  `**Chosen: B (supervisor wrapper).**` line above.

### Constants Phase 1 must apply versus the plan template

These three are the binding contract for Phase 1's reaper script. They are
mechanical drop-ins; the reaper's overall shape (curl + jq, status-code
branching, `kill -0` liveness, auth backoff, session-manager integration) is
unaffected.

1. **Bearer JSON path** is `.claudeAiOauth.accessToken` (not
   `.accessToken // .bearer // .token`). Update `BEARER_KEY` constant. Phase 1
   should compile the jq expression with `// empty` plus a hard-fail when
   empty so a future credential-format drift surfaces loudly instead of
   producing an empty bearer that 401s the DELETE.
2. **Org UUID source** is `~/.claude.json`, key `.oauthAccount.organizationUuid`
   (not `~/.claude/config.json` `.organizationUuid`). Update `ORG_UUID_PATH`
   and `ORG_UUID_KEY` constants.
3. **DELETE requires `anthropic-beta: environments-2025-11-01`.** Add this
   header to every reaper request.
