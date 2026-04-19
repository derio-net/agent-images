# Persistent Agent Reliability Implementation Plan

> **For VK agents:** Use vk-execute to implement assigned phases.
> **For local execution:** Use subagent-driven-development or executing-plans.
> **For dispatch:** Use vk-dispatch to create Issues from this plan.

**Spec:** `docs/superpowers/specs/2026-04-18-persistent-agent-reliability-design.md`
**Status:** Not Started; K8s preStop deployment change tracked in `derio-net/frank#108`

**Goal:** Fix the reliability and observability issues in the Willikins persistent agent surfaced by the 2026-04-18 triage: phantom sessions accumulating in claude.ai, silently-broken audit pipeline, unrotated 332 MB session log, and vk-bridge warning spam.

**Architecture:** Changes concentrated in `scripts/session-manager.sh`, `scripts/guardrails-hook.py`, and `scripts/vk-issue-bridge.py`. A new `scripts/shutdown.sh` and a new `scripts/logrotate.conf` are added, plus a new supercronic entry for rotation. If Phase 0 determines a K8s preStop hook is needed, the deployment change is filed as a separate Issue against `derio-net/frank` — not included in this plan's PR chain.

**Tech Stack:** Bash, Python 3.11+, pytest, supercronic, logrotate.

---

## Phase 0: Remote-control close/list spike [agentic]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/15 -->

### Task 1: Investigate Claude CLI for session/env management

**Files:**
- Create: `docs/findings/2026-04-18-remote-control-shutdown.md`

- [ ] **Step 1: Survey `claude` CLI surface**

```bash
claude --version 2>&1
claude --help 2>&1 | tail -60
claude remote-control --help 2>&1
```

Capture output verbatim. Look specifically for subcommands named `list`, `close`, `disconnect`, `stop`, `rm`, `logout`, or flags like `--session-id`, `--env-id`.

- [ ] **Step 2: Inspect Claude state dir for env/session bookkeeping**

```bash
ls -la ~/.claude/ 2>&1
find ~/.claude -type f \( -name '*.json' -o -name '*.jsonl' \) 2>&1 | head -30
```

If state files mention `env_`, `session_`, or `remote_control`, `jq` the relevant ones to understand the schema. Do not modify anything — read-only inspection.

- [ ] **Step 3: Probe for a server-side disconnect endpoint**

Check whether Claude Code's HTTP client (node bundle) exposes a disconnect RPC. Grep the installed bundle:

```bash
which claude
realpath "$(which claude)" 2>&1
CLAUDE_BIN="$(realpath "$(which claude)")"
# Find adjacent node modules or source
ls -la "$(dirname "$CLAUDE_BIN")/../lib" 2>&1 | head
grep -l "remote[-_]control" "$(dirname "$CLAUDE_BIN")/../lib/node_modules" -r 2>&1 | head -5 || true
```

Grep any hits for URL patterns like `/api/remote_control`, `disconnect`, `close_environment`. Do not call any endpoint — this is reconnaissance only.

- [ ] **Step 4: Test SIGTERM/SIGINT behavior in a sandbox**

On the pod (not in production), start a short-lived remote-control session and observe what signals do:

```bash
# In a separate shell on the pod:
nohup bash -c "echo y | claude remote-control --name spike-test" \
  > /tmp/spike.log 2>&1 &
SPIKE_PID=$!
sleep 10
# See child tree
pstree -p "$SPIKE_PID" 2>&1 || ps --ppid "$SPIKE_PID" 2>&1
# Test SIGTERM propagation
kill -TERM "$SPIKE_PID"
sleep 5
# Did anything in ~/.claude change? Does the session still show in claude.ai?
tail -30 /tmp/spike.log
```

Capture: does SIGTERM reach the child? Does it write any "disconnecting" log line? Does the session disappear from claude.ai UI, or linger?

Repeat with SIGINT.

- [ ] **Step 5: Write findings doc and commit**

Create `docs/findings/2026-04-18-remote-control-shutdown.md` with four sections:

```markdown
# Remote-Control Shutdown — Findings

## CLI surface
[verbatim relevant output from Step 1]

## State dir
[what's stored locally; does anything help?]

## Server endpoint
[whether a disconnect RPC exists, with evidence]

## Signal behavior
[what SIGTERM / SIGINT actually do to a live session]

## Decision for Phase 1

One of:
- **A (close API available):** call `claude remote-control close <name>` / HTTP endpoint in shutdown.sh.
- **B (signal-only):** SIGTERM → wait → SIGKILL fallback; document that phantoms will still accumulate at a reduced rate.
- **C (no clean shutdown possible):** document limitation, file upstream feature request, ship only SIGTERM trap + audit/rotation fixes.

**Chosen:** <A|B|C>. Reason: <one paragraph>.
```

Commit:

```bash
git add docs/findings/2026-04-18-remote-control-shutdown.md
git commit -m "docs: remote-control shutdown findings (Phase 0)"
```

Phase 1 implementer reads this file before starting.

---

## Phase 1: Housekeeping batch [agentic]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/16 -->

> **Note on phase ordering:** Housekeeping is logically independent of the Phase 0 spike, but placed at Phase 1 for strict linear dispatch ordering. It still blocks on Phase 0 only in the dispatch graph sense, not semantically.

### Task 1: Failing test — audit hook writes to audit.jsonl

**Files:**
- Modify: `tests/test_guardrails_hook.py` (create if missing)

- [ ] **Step 1: Confirm test layout**

```bash
ls tests/test_guardrails_hook.py 2>&1 || echo "missing — will create"
python -m pytest --version 2>&1
```

- [ ] **Step 2: Write failing test for PostToolUse Bash audit write**

Create or extend `tests/test_guardrails_hook.py`:

```python
"""Tests for guardrails-hook.py — PostToolUse audit write path."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).parent.parent / "scripts" / "guardrails-hook.py"


def _run_hook(payload: dict, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


def test_posttooluse_bash_writes_audit_line(tmp_path, monkeypatch):
    audit_log = tmp_path / "audit.jsonl"
    # Hook expands ~ — point HOME so AUDIT_LOG lands in tmp_path
    fake_home = tmp_path
    (fake_home / ".willikins-agent").mkdir(parents=True, exist_ok=True)
    expected_log = fake_home / ".willikins-agent" / "audit.jsonl"

    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
        "tool_response": {"exit_code": 0},
        "session_id": "test-session-42",
    }

    result = _run_hook(payload, {"HOME": str(fake_home)})
    assert result.returncode == 0, f"hook exited non-zero: {result.stderr}"

    assert expected_log.exists(), (
        f"audit.jsonl was not created at {expected_log}. "
        f"hook stderr: {result.stderr}"
    )
    lines = expected_log.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["command"] == "ls -la"
    assert entry["exit_code"] == 0
    assert entry["session"] == "test-session-42"


def test_posttooluse_non_bash_no_write(tmp_path):
    fake_home = tmp_path
    (fake_home / ".willikins-agent").mkdir(parents=True, exist_ok=True)
    expected_log = fake_home / ".willikins-agent" / "audit.jsonl"

    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "/etc/passwd"},
        "tool_response": {},
        "session_id": "t",
    }
    result = _run_hook(payload, {"HOME": str(fake_home)})
    assert result.returncode == 0
    assert not expected_log.exists()
```

Run:

```bash
python -m pytest tests/test_guardrails_hook.py -x 2>&1 | tail -20
```

Expected: `test_posttooluse_bash_writes_audit_line` FAILS because the hook reads `data.get("hook_type")` but Claude Code sends `hook_event_name` (verify by reading `scripts/guardrails-hook.py:205` and `:215`).

### Task 2: Fix audit hook key mismatch

**Files:**
- Modify: `scripts/guardrails-hook.py`

- [ ] **Step 1: Inspect current payload key usage**

```bash
grep -n 'hook_type\|hook_event_name' scripts/guardrails-hook.py
```

Expected: `hook_type` used in `main()` and nowhere does the hook accept `hook_event_name`.

- [ ] **Step 2: Accept both keys, preferring the current one**

In `scripts/guardrails-hook.py` `main()`, replace:

```python
    hook_type = data.get("hook_type", "")
```

with:

```python
    hook_type = data.get("hook_event_name") or data.get("hook_type", "")
```

Also update the `tool_output` key used by `handle_posttooluse`: Claude Code now sends `tool_response`. Change line 151:

```python
    exit_code = data.get("tool_output", {}).get("exit_code", None)
```

to:

```python
    tool_result = data.get("tool_response") or data.get("tool_output") or {}
    exit_code = tool_result.get("exit_code", None)
```

- [ ] **Step 3: Re-run tests**

```bash
python -m pytest tests/test_guardrails_hook.py -x 2>&1 | tail -10
```

Expected: both tests pass.

- [ ] **Step 4: Smoke check against a real payload example**

Capture (or reference) a real Claude Code hook payload from `session-willikins.log` if available; otherwise synthesize one matching the current documented schema. Confirm `test_posttooluse_bash_writes_audit_line` covers the current wire format.

### Task 3: Log rotation for session-*.log

**Files:**
- Create: `scripts/logrotate.conf`
- Create: `scripts/rotate-logs.sh`
- Modify: `crontab.txt`

- [ ] **Step 1: Write logrotate config**

Create `scripts/logrotate.conf`:

```
/home/claude/.willikins-agent/session-*.log {
    size 50M
    rotate 5
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
    dateformat -%Y%m%d-%s
}

/home/claude/.willikins-agent/vk-bridge.log
/home/claude/.willikins-agent/session-manager.log
/home/claude/.willikins-agent/audit.jsonl
{
    size 20M
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

`copytruncate` avoids corrupting a log file actively being written by `claude remote-control` (the process keeps its fd open).

- [ ] **Step 2: Write wrapper script**

Create `scripts/rotate-logs.sh`:

```bash
#!/usr/bin/env bash
# rotate-logs.sh — invoke logrotate against willikins-agent log dir
set -euo pipefail

CONF="/opt/scripts/logrotate.conf"
STATE="/home/claude/.willikins-agent/logrotate.state"

if ! command -v logrotate >/dev/null 2>&1; then
  echo "logrotate not installed — skipping" >&2
  exit 0
fi

logrotate --state "$STATE" "$CONF"
```

```bash
chmod +x scripts/rotate-logs.sh
```

- [ ] **Step 3: Verify logrotate is present in the image**

```bash
grep -nE 'logrotate' Dockerfile 2>&1 || echo "not found — need to add apt install"
```

If missing, add `logrotate` to the package install line in `Dockerfile`.

- [ ] **Step 4: Add hourly cron entry**

In `crontab.txt`, append before the "Audit digest" line:

```
# Log rotation (hourly)
7 * * * * /opt/scripts/rotate-logs.sh >> /home/claude/.willikins-agent/logrotate.log 2>&1
```

- [ ] **Step 5: Dry-run test**

```bash
# Requires logrotate installed locally; otherwise skip and test in pod post-deploy
mkdir -p /tmp/willtest/.willikins-agent
printf 'x%.0s' {1..60000000} > /tmp/willtest/.willikins-agent/session-willikins.log
sed 's|/home/claude|/tmp/willtest|g' scripts/logrotate.conf > /tmp/willtest/conf
logrotate -d --state /tmp/willtest/state /tmp/willtest/conf 2>&1 | head -20
```

Expected: output shows `log needs rotating (log size is ... size threshold is ...)`.

### Task 4: vk-bridge — skip repos with no GitHub remote-side presence

**Files:**
- Modify: `scripts/vk-issue-bridge.py`
- Modify: `tests/test_vk_issue_bridge.py`

- [ ] **Step 1: Read current behavior**

```bash
sed -n '350,390p' scripts/vk-issue-bridge.py
```

Confirm the flow: `discover_repos()` scans `~/repos/`, loop runs `gh issue list --repo derio-net/<name>` for each, logs `[warn] gh issue list failed for {repo}` on any error.

- [ ] **Step 2: Failing test — 404 on a repo should be demoted from warn to debug-or-silent**

Add to `tests/test_vk_issue_bridge.py`:

```python
class TestDiscoveryWarningFiltering:
    def test_gh_404_is_not_a_warn(self, monkeypatch, capsys):
        mod = _load_bridge()
        import subprocess
        def fake_run(*args, **kwargs):
            raise subprocess.CalledProcessError(
                1, "gh",
                stderr="HTTP 404: Not Found (https://api.github.com/repos/derio-net/derio-profile/issues)",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)
        # Call whatever the loop helper is — adjust to the real function name
        # once the implementer identifies it. This is a placeholder contract.
        issues = mod.gh_list_ready_issues("derio-net/derio-profile")
        assert issues == []
        # Assert the log line, if log() writes to stderr, does NOT include "[warn]"
        captured = capsys.readouterr()
        assert "[warn]" not in captured.err or "derio-profile" not in captured.err
```

Run:

```bash
python -m pytest tests/test_vk_issue_bridge.py::TestDiscoveryWarningFiltering -x 2>&1 | tail -10
```

Expected: FAIL (bridge currently emits `[warn]`).

- [ ] **Step 3: Downgrade 404 to info, keep other errors as warn**

In `gh_list_ready_issues` (around line 374), change the `except` branch to inspect stderr:

```python
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            if "HTTP 404" in stderr or "Could not resolve" in stderr:
                # Repo not present on GitHub (e.g., local-only mirror). Informational, not an alert.
                log(f"[info] gh list skipped — {repo}: no GitHub remote ({stderr.splitlines()[0] if stderr else ''})")
            else:
                log(f"[warn] gh issue list failed for {repo}: {stderr}")
            continue
```

- [ ] **Step 4: Re-run full bridge suite**

```bash
python -m pytest tests/ 2>&1 | tail -15
```

Expected: pass.

### Task 5: Phase 1 PR

- [ ] **Step 1: Open PR**

```bash
git checkout -b phase1/housekeeping
git add scripts/guardrails-hook.py scripts/logrotate.conf scripts/rotate-logs.sh \
        scripts/vk-issue-bridge.py crontab.txt tests/
# Dockerfile edit only if logrotate was missing
git status
git commit -m "fix(agent): audit hook payload keys + log rotation + vk-bridge 404 demotion"
```

Push and open a PR. No production deploy yet — Phase 3 soaks the whole bundle together.

---

## Phase 2: Graceful shutdown [agentic]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/17 -->

> **Semantic dependency:** Phase 0 findings doc must exist (`docs/findings/2026-04-18-remote-control-shutdown.md`). Phase 2 branches on its Decision section. Phase 2 also inherits the dispatch-graph `Blocked by` link to Phase 1 (housekeeping); in practice that's a no-op since the Phase 1 PR is unrelated.

### Task 1: Write shutdown script

**Files:**
- Create: `scripts/shutdown.sh`
- Create: `tests/test_shutdown.sh` (or extend an existing bash test harness)

- [ ] **Step 1: Read Phase 0 decision**

```bash
cat docs/findings/2026-04-18-remote-control-shutdown.md
```

Identify chosen path (A / B / C). This determines whether `shutdown.sh` calls a close API, sends a specific signal sequence, or is a no-op wrapper that only cleans PID files.

- [ ] **Step 2: Write shutdown.sh skeleton (signal-based baseline)**

Create `scripts/shutdown.sh`:

```bash
#!/usr/bin/env bash
# shutdown.sh — gracefully terminate all willikins-agent remote-control sessions
# Invoked by K8s preStop hook OR by ad-hoc operator.
set -euo pipefail

LOGFILE="/home/claude/.willikins-agent/shutdown.log"
PIDDIR="/home/claude/.willikins-agent/pids"
mkdir -p "$(dirname "$LOGFILE")" "$PIDDIR"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE" >&2; }

if [[ ! -d "$PIDDIR" ]]; then
  log "no PID dir — nothing to shut down"
  exit 0
fi

shopt -s nullglob
pids_seen=0
for pidfile in "$PIDDIR"/*.pid; do
  pids_seen=1
  name="$(basename "$pidfile" .pid)"
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [[ -z "$pid" ]] && { log "empty pidfile $pidfile — skipping"; continue; }

  if ! kill -0 "$pid" 2>/dev/null; then
    log "session '$name' PID $pid already dead — cleaning"
    rm -f "$pidfile"
    continue
  fi

  # --- Phase 0 Decision injection point ---
  # Path A: close via CLI or HTTP first
  #   claude remote-control close --name "$name" || log "close returned nonzero"
  # Path B/C: signal-only
  log "sending SIGTERM to '$name' (PID $pid)"
  kill -TERM "$pid" || log "SIGTERM to $pid returned nonzero"
done

if (( pids_seen == 0 )); then
  log "no PID files present"
  exit 0
fi

# Wait up to 20s for graceful exit, then SIGKILL stragglers
deadline=$(( $(date +%s) + 20 ))
while (( $(date +%s) < deadline )); do
  alive=0
  for pidfile in "$PIDDIR"/*.pid; do
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && alive=1
  done
  (( alive == 0 )) && break
  sleep 1
done

for pidfile in "$PIDDIR"/*.pid; do
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [[ -z "$pid" ]] && continue
  if kill -0 "$pid" 2>/dev/null; then
    log "SIGKILL straggler $pid"
    kill -KILL "$pid" || true
  fi
  rm -f "$pidfile"
done

log "shutdown complete"
```

```bash
chmod +x scripts/shutdown.sh
```

If Phase 0 chose Path A, uncomment the `claude remote-control close` block and remove/adjust the comment marker. If Path C, replace the signal block with a `log "no clean shutdown available"` line.

- [ ] **Step 3: Tests for shutdown.sh**

Create `tests/test_shutdown.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP"
mkdir -p "$HOME/.willikins-agent/pids"

# Start a sleep-forever child that handles SIGTERM
bash -c 'trap "exit 0" TERM; sleep 300 &
         echo $! > '"$HOME"'/.willikins-agent/pids/fake.pid; wait' &
HARNESS_PID=$!
sleep 1

# Actually put the child's PID in the pidfile
CHILD_PID="$(cat "$HOME/.willikins-agent/pids/fake.pid")"

# Verify child is alive
kill -0 "$CHILD_PID" || { echo "FAIL: harness child not running"; exit 1; }

# Run shutdown.sh
bash scripts/shutdown.sh

# Child should be dead and pidfile gone
if kill -0 "$CHILD_PID" 2>/dev/null; then
  echo "FAIL: child $CHILD_PID still alive after shutdown.sh"
  exit 1
fi
if [[ -f "$HOME/.willikins-agent/pids/fake.pid" ]]; then
  echo "FAIL: pidfile not cleaned"
  exit 1
fi

echo "OK"
```

```bash
chmod +x tests/test_shutdown.sh
bash tests/test_shutdown.sh 2>&1
```

Expected: `OK`.

### Task 2: Wire shutdown into session-manager + supercronic exit

**Files:**
- Modify: `scripts/session-manager.sh`
- Modify: `entrypoint.sh` (if it supervises supercronic)

- [ ] **Step 1: Review entrypoint**

```bash
cat entrypoint.sh
```

Confirm whether it invokes `supercronic` in foreground or backgrounds it with `wait -n`. The goal: on container SIGTERM, entrypoint must run `shutdown.sh` before exiting.

- [ ] **Step 2: Add trap in entrypoint.sh**

If entrypoint.sh ends with `exec supercronic ...`, replace with:

```bash
# Trap SIGTERM to gracefully disconnect remote-control sessions before exit
shutdown_handler() {
  echo "[entrypoint] SIGTERM received — running shutdown.sh"
  /opt/scripts/shutdown.sh || true
  exit 0
}
trap shutdown_handler TERM INT

supercronic /home/claude/.crontab &
SUPERCRONIC_PID=$!
wait "$SUPERCRONIC_PID"
```

If entrypoint already has a trap / supervisor loop, add the shutdown.sh call inside it.

- [ ] **Step 3: Verify trap locally**

Using a Docker smoke test (optional if not available locally):

```bash
docker build -t secure-agent-kali:test . 2>&1 | tail -5
docker run -d --name sak-test secure-agent-kali:test
sleep 15
docker stop --time=30 sak-test
docker logs sak-test 2>&1 | grep -i shutdown
```

Expected: log line `[entrypoint] SIGTERM received — running shutdown.sh` and subsequent lines from shutdown.sh.

```bash
docker rm -f sak-test 2>/dev/null || true
```

### Task 3: K8s preStop hook (frank-side) — filed as separate Issue

**Files:**
- None in this repo. Change lives in `derio-net/frank`.

- [ ] **Step 1: Open a tracking Issue against derio-net/frank**

```bash
gh issue create --repo derio-net/frank \
  --title "secure-agent-pod: add preStop hook for graceful session shutdown" \
  --body "$(cat <<'EOF'
Part of secure-agent-kali plan `2026-04-18-persistent-agent-reliability.md` Phase 1.

Add a preStop hook to the `secure-agent-pod` Deployment pointing at `/opt/scripts/shutdown.sh`:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/opt/scripts/shutdown.sh"]
```

And raise `terminationGracePeriodSeconds` to at least `45` (shutdown.sh allows 20s for SIGTERM + margin).

Depends on: secure-agent-kali image including `shutdown.sh` (shipped in this plan's Phase 1/2 PRs).

## Acceptance
- Pod redeploy triggers preStop, `shutdown.sh` runs to completion, no orphaned `claude remote-control` processes on the new pod after rollout.
EOF
)"
```

- [ ] **Step 2: Link in the plan**

Record the Issue number in this plan's header (manually edit the Status line to include `; frank#<N>`) so future readers can follow the cross-repo dependency.

### Task 4: Phase 2 PR

- [ ] **Step 1: Open PR**

```bash
git checkout -b phase2/graceful-shutdown
git add scripts/shutdown.sh entrypoint.sh tests/test_shutdown.sh docs/findings/
git commit -m "feat(agent): graceful shutdown for remote-control sessions"
```

PR body should reference the frank Issue created in Task 3. No deploy yet — Phase 3 handles.

---

## Phase 3: 24h soak [manual]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/18 -->

### Task 1: Deploy

- [ ] **Step 1: Merge Phase 1 and Phase 2 PRs**

In any order; they touch different files.

- [ ] **Step 2: Rebuild image and roll pod**

```bash
# Whatever the standard build path is for secure-agent-kali
gh workflow run build.yml --repo derio-net/secure-agent-kali --ref main 2>&1
# Once the new image tag lands, bump the frank deployment and merge the preStop PR
```

- [ ] **Step 3: Capture baseline**

```bash
START_TS=$(date -u +%FT%T)
echo "$START_TS" > /tmp/soak-start.txt
# Claude.ai phantom count (manual — open the app, count entries)
# Session log size, audit line count
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- \
  bash -c 'stat -c "%s" ~/.willikins-agent/session-willikins.log 2>/dev/null;
           wc -l ~/.willikins-agent/audit.jsonl 2>/dev/null;
           ls ~/.willikins-agent/pids/'
```

### Task 2: Observe for 24h

- [ ] **Step 1: Check at T+2h, T+8h, T+24h**

At each checkpoint, record:

```bash
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- \
  bash -c '
    echo "== session-manager restarts =="
    grep -c "Starting session" ~/.willikins-agent/session-manager.log
    echo "== disconnect events =="
    grep -c "Server unreachable" ~/.willikins-agent/session-willikins.log || true
    echo "== audit lines =="
    wc -l ~/.willikins-agent/audit.jsonl 2>/dev/null || echo "0 (still missing)"
    echo "== log size =="
    du -h ~/.willikins-agent/session-willikins.log
    echo "== logrotate state =="
    cat ~/.willikins-agent/logrotate.state 2>/dev/null | tail -5
    echo "== vk-bridge warnings =="
    grep -c "\[warn\]" ~/.willikins-agent/vk-bridge.log
  '
```

- [ ] **Step 2: Manual phantom count in claude.ai**

At T+24h, count remote-control environments in the claude.ai UI. Compare with the baseline and with the number of session-manager restarts during the window. If phantoms ≈ restarts: shutdown is not cleanly disconnecting (go back to Phase 0 with new signal/API evidence). If phantoms ≪ restarts: graceful shutdown is working.

### Task 3: Outcome note and follow-up decisions

- [ ] **Step 1: Write outcome note**

Append a short entry to `../willikins/decisions/log.md` (via a separate commit in the willikins repo):

```
[2026-04-XX] DECISION: <reliability plan outcome> | REASONING: <phantom delta, audit state, disconnect count> | CONTEXT: persistent-agent-reliability plan (secure-agent-kali 2026-04-18)
```

- [ ] **Step 2: Open follow-up plans if needed**

- If disconnect loops (`Server unreachable for 11 minutes`) persist at > 1/day: open a new plan **against derio-net/frank** for egress/Cilium investigation. Do not expand scope of this plan.
- If phantoms still accumulate despite graceful shutdown: open an upstream feature request with Anthropic documenting the findings doc.
- If audit.jsonl is still empty: the key-mismatch fix is not the whole problem — open a debug plan against secure-agent-kali.

- [ ] **Step 3: Mark Status complete**

Edit the `Status:` header of this plan to `Complete` and of the spec to `Complete`.
