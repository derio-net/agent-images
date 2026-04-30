# Silent-Reconnect Phantom Reaper Implementation Plan

> **For VK agents:** Use vk-execute to implement assigned phases.
> **For local execution:** Use subagent-driven-development or executing-plans.
> **For dispatch:** Use vk-dispatch to create Issues from this plan.

**Spec:** `docs/superpowers/specs/2026-04-22-silent-reconnect-phantoms-design.md`
**Status:** Not Started

**Goal:** Close the phantom-session leak surfaced by the 2026-04-18 persistent-agent-reliability T+48h soak (17 phantoms: ~11 silent-reconnects + ~6 OOMKills) by adding a client-driven orphan-env reaper invoked inline from `kali/scripts/session-manager.sh` on each 5-minute tick.

**Context:** Phase 2 of the original plan wired `shutdown.sh` as a K8s `preStop` hook, which deregisters the bridge env cleanly on pod drain. It cannot help when claude dies without receiving SIGTERM — i.e., when the vk-local tunnel closes claude's stdin (`<(echo y)`), when OOMKiller sends SIGKILL, or when a sibling-process termination cascades into claude. In all those paths, the `[bridge:shutdown]` handler never runs and `DELETE /v1/environments/bridge/<env_id>` is never called. The reaper closes that gap by detecting orphaned envs and calling DELETE ourselves.

**Architecture:** One new script (`kali/scripts/reap-orphan-envs.sh` — Branch A default), one `session-manager.sh` integration, one test file. If Phase 0 finds that `bridge-pointer.json` does not survive `kill -9`, the plan branches to Branch B: a ~60-LOC Python supervisor (`kali/scripts/wrap-claude.py`) that tracks env_id in a file we own, with the reaper reading that file instead. Branch is pre-committed so Phase 1 can start immediately after Phase 0 lands.

**Tech Stack:** Bash (Branch A), Python 3.11 (Branch B only), `jq`, `curl`, `pytest`, `bash` test harness.

**Scope boundary:** This plan does **not** change any `derio-net/frank` manifests (no new preStop or grace-period changes — existing Phase 2 wiring is sufficient), does **not** reduce OOMKill *frequency* (owned by `2026-04-22-vk-local-memory-profile.md`), and does **not** touch `WILLIKINS_REPOS` multi-session expansion. It ships only the orphan cleanup mechanism and a 48h soak.

---

## Phase 0: Recon spike [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/29 -->

**Depends on:** —

### Task 1: Live-verify pointer survival, credentials, DELETE signature

**Files:**
- Create: `kali/docs/findings/2026-04-22-orphan-env-reaper.md`

- [x] **Step 1: Baseline inspection on the pod**

```bash
source .env_devops 2>/dev/null || true  # if the op runs on the Frank host
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  echo "=== claude version ==="
  claude --version
  echo "=== state dir ==="
  ls -la ~/.claude/
  echo "=== existing pointers ==="
  find ~/.claude/projects -name bridge-pointer.json 2>/dev/null | head -10
  echo "=== credentials file presence ==="
  ls -la ~/.claude/.credentials.json ~/.claude/config.json ~/.claude/state.json 2>/dev/null || true
'
```

Capture output verbatim into findings doc Section 1.

- [x] **Step 2: Start a throwaway bridge**

On the pod, in a side shell (not the session-manager-managed willikins session):

```bash
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  cd /tmp && mkdir -p spike-reaper && cd spike-reaper
  git init -q 2>/dev/null
  nohup bash -c "exec claude remote-control --name spike-reaper-2026-04-22 < <(echo y)" \
    > /tmp/spike-reaper.log 2>&1 &
  echo $!
'
```

Record the returned PID (call it `$SPIKE_PID`). Wait 15s, then:

```bash
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  find ~/.claude/projects -path "*spike-reaper*" -name bridge-pointer.json
  find ~/.claude/projects -path "*spike-reaper*" -name bridge-pointer.json -exec cat {} \; | head
  tail -20 /tmp/spike-reaper.log
'
```

Expected: pointer file exists; log shows a `registered environment` or similar line with `env_…` id. Capture both verbatim into findings Section 2.

- [x] **Step 3: SIGKILL and verify pointer survival**

```bash
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  # Find the claude PID (not our bash wrapper)
  pgrep -f "claude remote-control --name spike-reaper" | head -1 | xargs -I{} kill -9 {}
  sleep 3
  echo "=== after SIGKILL ==="
  pgrep -f "claude remote-control --name spike-reaper" || echo "claude gone"
  echo "=== pointer survival ==="
  find ~/.claude/projects -path "*spike-reaper*" -name bridge-pointer.json
  find ~/.claude/projects -path "*spike-reaper*" -name bridge-pointer.json -exec cat {} \;
'
```

Record in findings Section 3:
- Is claude process gone? (expected: yes)
- Does the pointer file still exist? (decides Branch A vs B)
- If yes, what fields does the JSON contain? Does it include an originating PID?

- [x] **Step 4: Locate organization UUID**

```bash
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  echo "=== credentials.json ==="
  jq -r "keys" ~/.claude/.credentials.json 2>/dev/null || cat ~/.claude/.credentials.json
  echo "=== config.json ==="
  cat ~/.claude/config.json 2>/dev/null | head -50
  echo "=== state ==="
  ls ~/.claude/state* ~/.claude/*state* 2>/dev/null
  echo "=== grep for organization ==="
  grep -rIn "organization" ~/.claude/ --include="*.json" 2>/dev/null | head -20
'
```

Record in findings Section 4: exact path + JSON key for the org UUID. If absent from state, fall back to the CLI bundle: `strings "$(realpath "$(which claude)")" | grep -i organization | head`.

- [x] **Step 5: Compose and verify a working DELETE**

Using the env_id captured in Step 3 and the bearer/org UUID from Step 4, compose a curl:

```bash
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  BEARER=$(jq -r ".accessToken // .bearer // .token" ~/.claude/.credentials.json)
  ORG_UUID=$(jq -r "<field discovered in Step 4>" <path discovered in Step 4>)
  ENV_ID="env_<id from Step 3>"
  curl -fsS -X DELETE \
    -H "Authorization: Bearer $BEARER" \
    -H "x-organization-uuid: $ORG_UUID" \
    "https://api.anthropic.com/v1/environments/bridge/$ENV_ID" \
    -w "\nHTTP %{http_code}\n"
'
```

Expected: HTTP 200 or 204. Verify in the claude.ai UI that the `spike-reaper-2026-04-22` environment disappears within 30s. Record the exact curl that worked.

- [x] **Step 6: TTL observation (non-gating)**

If curl DELETE succeeded, this step is empty. If DELETE failed and we left the env orphan, note the time. At Step 8 (findings writeup), check claude.ai again — did the env disappear on its own? Record the delta. This informs whether the reaper is "strict cleanup" or "belt-and-suspenders."

- [x] **Step 7: Cleanup**

```bash
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  rm -rf /tmp/spike-reaper /tmp/spike-reaper.log
  find ~/.claude/projects -path "*spike-reaper*" -exec rm -rf {} + 2>/dev/null || true
'
```

- [x] **Step 8: Write findings doc**

Create `kali/docs/findings/2026-04-22-orphan-env-reaper.md` with five sections:

```markdown
# Orphan-Env Reaper — Findings

## Pointer survival under SIGKILL
[verbatim Step 3 output; one-line conclusion: survived | did not survive]

## Pointer JSON shape
[fields; presence of env_id, pid, other]

## Organization UUID location
[path + key, with example value redacted]

## DELETE signature
[exact working curl invocation from Step 5]

## TTL note (optional)
[observed / not applicable / n/a]

## Decision for Phase 1

One of:
- **A (pointer-based reaper):** `bridge-pointer.json` survives SIGKILL and exposes env_id. Phase 1 builds `reap-orphan-envs.sh` that scans these pointers.
- **B (supervisor wrapper):** pointer does not survive SIGKILL. Phase 1 adds `wrap-claude.py` supervisor that records env_id to `~/.willikins-agent/envs/<session>.json` on registration and preserves on crash; reaper scans that dir.

**Chosen:** <A | B>.

**Reason:** <one paragraph>.
```

Commit:

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images
git add kali/docs/findings/2026-04-22-orphan-env-reaper.md
git commit -m "docs(findings): orphan-env reaper recon (Phase 0)"
```

Phase 1 Task 1 reads this file and branches on the Decision section.

---

## Phase 1: Reaper implementation [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/30 -->

**Depends on:** Phase 0

### Task 1: Read Phase 0 decision and confirm branch

**Files:**
- Read: `kali/docs/findings/2026-04-22-orphan-env-reaper.md`

- [ ] **Step 1: Confirm chosen branch**

```bash
grep -A2 "^**Chosen:**\|^## Decision for Phase 1" kali/docs/findings/2026-04-22-orphan-env-reaper.md
```

Record the chosen letter in this session's scratch notes. All subsequent tasks reference it. The remainder of this phase has two branches; execute only the one Phase 0 chose.

### Task 2: Failing tests for the reaper (Branch A — pointer-based)

> **Execute only if Phase 0 Decision == A. Otherwise skip to Task 4 (Branch B).**

**Files:**
- Create: `kali/tests/test_reap_orphan_envs.sh`

- [ ] **Step 1: Write the bash test harness**

Create `kali/tests/test_reap_orphan_envs.sh`:

```bash
#!/usr/bin/env bash
# test_reap_orphan_envs.sh — harness for scripts/reap-orphan-envs.sh
set -euo pipefail

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP"
export WILLIKINS_AGENT_DIR="$TMP/.willikins-agent"
mkdir -p "$HOME/.claude/projects/dead-a" \
         "$HOME/.claude/projects/live-b" \
         "$WILLIKINS_AGENT_DIR"

# Fake credentials & org UUID
cat > "$HOME/.claude/.credentials.json" <<'EOF'
{"accessToken":"sk-ant-test-bearer","bearer":"sk-ant-test-bearer"}
EOF
cat > "$HOME/.claude/config.json" <<'EOF'
{"organizationUuid":"org-uuid-test-000"}
EOF

# Pointer for a dead-PID env (use PID 999999 — almost certainly dead)
cat > "$HOME/.claude/projects/dead-a/bridge-pointer.json" <<'EOF'
{"env_id":"env_orphan_A","pid":999999}
EOF

# Pointer for a live env — bind to our own test PID so kill -0 succeeds
printf '{"env_id":"env_live_B","pid":%d}\n' "$$" \
  > "$HOME/.claude/projects/live-b/bridge-pointer.json"

# Stub curl: prepend a shim dir to PATH
STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/curl" <<'EOF'
#!/usr/bin/env bash
# Record invocation args + stdin, return canned status based on $CURL_STUB_CODE.
echo "curl $*" >> "$CURL_LOG"
code="${CURL_STUB_CODE:-200}"
printf '\nHTTP %s\n' "$code"
# Exit matches curl --fail: 0 on 2xx, 22 on >=400.
if [[ "$code" =~ ^2 ]]; then exit 0; else exit 22; fi
EOF
chmod +x "$STUB_DIR/curl"
export PATH="$STUB_DIR:$PATH"
export CURL_LOG="$TMP/curl.log"

# --- Test 1: happy path (dead-a reaped, live-b untouched) ---
: > "$CURL_LOG"
CURL_STUB_CODE=200 bash "$(cd "$(dirname "$0")/.." && pwd)/scripts/reap-orphan-envs.sh"

grep -q "env_orphan_A" "$CURL_LOG" || { echo "FAIL: no DELETE for env_orphan_A"; exit 1; }
grep -q "env_live_B"   "$CURL_LOG" && { echo "FAIL: DELETE called for live env_live_B"; exit 1; } || true
[[ -f "$HOME/.claude/projects/dead-a/bridge-pointer.json" ]] && { echo "FAIL: dead pointer not removed"; exit 1; } || true
[[ -f "$HOME/.claude/projects/live-b/bridge-pointer.json" ]] || { echo "FAIL: live pointer wrongly removed"; exit 1; }

# --- Test 2: 404 treated as success, pointer removed ---
cat > "$HOME/.claude/projects/dead-a/bridge-pointer.json" <<'EOF'
{"env_id":"env_orphan_A2","pid":999999}
EOF
: > "$CURL_LOG"
CURL_STUB_CODE=404 bash "$(cd "$(dirname "$0")/.." && pwd)/scripts/reap-orphan-envs.sh"
[[ -f "$HOME/.claude/projects/dead-a/bridge-pointer.json" ]] && { echo "FAIL: pointer not removed on 404"; exit 1; } || true

# --- Test 3: 401 treated as error, pointer left in place ---
cat > "$HOME/.claude/projects/dead-a/bridge-pointer.json" <<'EOF'
{"env_id":"env_orphan_A3","pid":999999}
EOF
: > "$CURL_LOG"
CURL_STUB_CODE=401 bash "$(cd "$(dirname "$0")/.." && pwd)/scripts/reap-orphan-envs.sh"
[[ -f "$HOME/.claude/projects/dead-a/bridge-pointer.json" ]] || { echo "FAIL: pointer removed despite 401"; exit 1; }

# --- Test 4: 5xx treated as transient, pointer left in place ---
cat > "$HOME/.claude/projects/dead-a/bridge-pointer.json" <<'EOF'
{"env_id":"env_orphan_A4","pid":999999}
EOF
: > "$CURL_LOG"
CURL_STUB_CODE=503 bash "$(cd "$(dirname "$0")/.." && pwd)/scripts/reap-orphan-envs.sh"
[[ -f "$HOME/.claude/projects/dead-a/bridge-pointer.json" ]] || { echo "FAIL: pointer removed despite 5xx"; exit 1; }

echo "OK"
```

```bash
chmod +x kali/tests/test_reap_orphan_envs.sh
bash kali/tests/test_reap_orphan_envs.sh 2>&1
```

Expected: FAIL (`scripts/reap-orphan-envs.sh` does not yet exist — bash will error on the sourcing line). This is the expected red state for TDD.

### Task 3: Implement the reaper (Branch A)

> **Execute only if Phase 0 Decision == A.**

**Files:**
- Create: `kali/scripts/reap-orphan-envs.sh`
- Modify: `kali/scripts/session-manager.sh`

- [ ] **Step 1: Write `reap-orphan-envs.sh`**

Paths referenced below (`ORG_UUID_PATH`, `ORG_UUID_KEY`, `BEARER_KEY`) must match what Phase 0 Step 4 recorded. The template uses the most likely values — adjust before commit.

Create `kali/scripts/reap-orphan-envs.sh`:

```bash
#!/usr/bin/env bash
# reap-orphan-envs.sh — DELETE orphaned claude remote-control bridge envs.
#
# Invoked by session-manager.sh on each 5-minute tick. Scans claude's own
# bridge-pointer.json files and, for any whose owning PID is gone, calls
# DELETE /v1/environments/bridge/<env_id> against the Anthropic API.
# See docs/findings/2026-04-22-orphan-env-reaper.md for reconnaissance.
set -euo pipefail

AGENT_DIR="${WILLIKINS_AGENT_DIR:-$HOME/.willikins-agent}"
LOGFILE="$AGENT_DIR/reap-orphan-envs.log"
AUTH_STATE="$AGENT_DIR/reap-auth-error.state"
AUTH_BACKOFF_SECS=3600
AUTH_FAIL_THRESHOLD=3
API_BASE="${CLAUDE_API_BASE:-https://api.anthropic.com}"
BEARER_PATH="$HOME/.claude/.credentials.json"
BEARER_KEY=".accessToken // .bearer // .token"
ORG_UUID_PATH="$HOME/.claude/config.json"
ORG_UUID_KEY=".organizationUuid // .organization_uuid"

mkdir -p "$AGENT_DIR"

log() {
  local msg="[$(date -u '+%Y-%m-%d %H:%M:%S')] [reap] $*"
  echo "$msg" >&2
  echo "$msg" >> "$LOGFILE" 2>/dev/null || true
}

# Respect auth-error backoff window
if [[ -f "$AUTH_STATE" ]]; then
  last_err=$(awk '{print $1}' "$AUTH_STATE" 2>/dev/null || echo 0)
  fail_count=$(awk '{print $2}' "$AUTH_STATE" 2>/dev/null || echo 0)
  if (( fail_count >= AUTH_FAIL_THRESHOLD )); then
    now=$(date +%s)
    if (( now - last_err < AUTH_BACKOFF_SECS )); then
      log "auth-backoff active (${fail_count} recent failures); skipping"
      exit 0
    fi
  fi
fi

shopt -s nullglob
pointers=( "$HOME/.claude/projects"/*/bridge-pointer.json )

if (( ${#pointers[@]} == 0 )); then
  exit 0
fi

# Lazily resolve credentials — only if we have orphans.
bearer=""; org_uuid=""
read_creds() {
  if [[ ! -f "$BEARER_PATH" ]]; then
    log "error: $BEARER_PATH missing"; return 1
  fi
  bearer=$(jq -r "$BEARER_KEY" "$BEARER_PATH" 2>/dev/null || true)
  if [[ -z "$bearer" || "$bearer" == "null" ]]; then
    log "error: could not extract bearer from $BEARER_PATH"; return 1
  fi
  if [[ ! -f "$ORG_UUID_PATH" ]]; then
    log "error: $ORG_UUID_PATH missing"; return 1
  fi
  org_uuid=$(jq -r "$ORG_UUID_KEY" "$ORG_UUID_PATH" 2>/dev/null || true)
  if [[ -z "$org_uuid" || "$org_uuid" == "null" ]]; then
    log "error: could not extract organization UUID from $ORG_UUID_PATH"; return 1
  fi
  return 0
}

auth_error=0
reaped=0

for pointer in "${pointers[@]}"; do
  env_id=$(jq -r '.env_id // .environmentId // empty' "$pointer" 2>/dev/null || true)
  pid=$(jq -r '.pid // empty' "$pointer" 2>/dev/null || true)
  if [[ -z "$env_id" ]]; then
    log "skip: no env_id in $pointer"
    continue
  fi
  # Liveness: if pid field present and process alive, keep pointer.
  if [[ -n "$pid" && "$pid" =~ ^[1-9][0-9]*$ ]] && kill -0 "$pid" 2>/dev/null; then
    continue
  fi

  if [[ -z "$bearer" ]]; then
    read_creds || { log "aborting — credentials unresolved"; exit 0; }
  fi

  log "DELETE $env_id (pointer=$pointer pid=${pid:-none})"
  # --fail returns 22 on HTTP >= 400. Capture status via -w.
  http_code=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE \
    -H "Authorization: Bearer $bearer" \
    -H "x-organization-uuid: $org_uuid" \
    "$API_BASE/v1/environments/bridge/$env_id" || echo "000")

  case "$http_code" in
    2*|404)
      log "reaped $env_id (HTTP $http_code)"
      rm -f "$pointer"
      reaped=$((reaped+1))
      ;;
    401|403)
      log "auth-error $env_id (HTTP $http_code) — leaving pointer"
      auth_error=1
      ;;
    5*)
      log "transient $env_id (HTTP $http_code) — leaving pointer"
      ;;
    *)
      log "unexpected $env_id (HTTP $http_code) — leaving pointer"
      ;;
  esac
done

# Update auth-backoff state
if (( auth_error == 1 )); then
  now=$(date +%s)
  prev=0
  [[ -f "$AUTH_STATE" ]] && prev=$(awk '{print $2}' "$AUTH_STATE" 2>/dev/null || echo 0)
  echo "$now $((prev+1))" > "$AUTH_STATE"
else
  rm -f "$AUTH_STATE"
fi

(( reaped > 0 )) && log "reaped $reaped orphan env(s)"
exit 0
```

```bash
chmod +x kali/scripts/reap-orphan-envs.sh
```

- [ ] **Step 2: Re-run the bash tests**

```bash
bash kali/tests/test_reap_orphan_envs.sh 2>&1
```

Expected: `OK` (all four test cases pass).

- [ ] **Step 3: Integrate into session-manager**

In `kali/scripts/session-manager.sh`, after the `SHUTDOWN_MARKER` check (around line 22) and before the `WILLIKINS_REPOS` validation, add:

```bash
# Reap any orphaned bridge envs before spawning new sessions. Non-fatal.
if [[ "${REAP_ORPHAN_ENVS:-1}" == "1" ]]; then
  "$(dirname "$0")/reap-orphan-envs.sh" 2>/dev/null \
    || log "[warn] reap-orphan-envs returned non-zero"
fi
```

- [ ] **Step 4: Smoke test on the pod (post-build)**

After the image is rebuilt and pushed (Task 5), roll the pod and trigger a stale-PID event manually:

```bash
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  # Capture current env_id
  POINTER=$(find ~/.claude/projects -name bridge-pointer.json | head -1)
  cat "$POINTER"
  # SIGKILL willikins to create an orphan
  pgrep -f "claude remote-control --name willikins" | head -1 | xargs -r kill -9
  sleep 310  # wait for two session-manager ticks
  tail -20 ~/.willikins-agent/reap-orphan-envs.log
'
```

Expected: log shows `reaped env_<id> (HTTP 200)` and the original env is gone from claude.ai. Defer to Phase 2 for the soak-level acceptance.

### Task 4: Implement supervisor wrapper (Branch B — conditional)

> **Execute only if Phase 0 Decision == B. If Decision == A, skip entirely.**

**Files:**
- Create: `kali/scripts/wrap-claude.py`
- Create: `kali/scripts/reap-orphan-envs.sh` (Branch B variant — scans `~/.willikins-agent/envs/`)
- Create: `kali/tests/test_wrap_claude.py`
- Modify: `kali/scripts/session-manager.sh`

- [ ] **Step 1: Failing test for wrap-claude.py**

Create `kali/tests/test_wrap_claude.py`:

```python
"""Tests for wrap-claude.py supervisor: envs file lifecycle."""
from __future__ import annotations
import json
import os
import signal
import subprocess
import time
from pathlib import Path

WRAP = Path(__file__).parent.parent / "scripts" / "wrap-claude.py"


def _fake_claude(tmp_path: Path) -> Path:
    """Write a script that prints a registration line then sleeps."""
    path = tmp_path / "fake-claude"
    path.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'registered environment env_TEST123' >&2\n"
        "trap 'exit 0' TERM\n"
        "sleep 300\n"
    )
    path.chmod(0o755)
    return path


def test_graceful_sigterm_clears_envs_file(tmp_path):
    agent_dir = tmp_path / ".willikins-agent"
    envs_dir = agent_dir / "envs"
    envs_dir.mkdir(parents=True)

    fake = _fake_claude(tmp_path)
    env = {
        **os.environ,
        "WILLIKINS_AGENT_DIR": str(agent_dir),
        "CLAUDE_BIN_OVERRIDE": str(fake),
    }
    proc = subprocess.Popen(
        ["python3", "-u", str(WRAP), "willikins-test"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for envs file
    target = envs_dir / "willikins-test.json"
    for _ in range(40):
        if target.exists():
            break
        time.sleep(0.1)
    assert target.exists(), f"envs file not created: {list(envs_dir.iterdir())}"
    data = json.loads(target.read_text())
    assert data["env_id"] == "env_TEST123"
    assert data["pid"] > 0

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    assert proc.returncode == 0
    assert not target.exists(), "envs file should be removed on graceful exit"


def test_sigkill_leaves_envs_file(tmp_path):
    agent_dir = tmp_path / ".willikins-agent"
    envs_dir = agent_dir / "envs"
    envs_dir.mkdir(parents=True)

    fake = _fake_claude(tmp_path)
    env = {
        **os.environ,
        "WILLIKINS_AGENT_DIR": str(agent_dir),
        "CLAUDE_BIN_OVERRIDE": str(fake),
    }
    proc = subprocess.Popen(
        ["python3", "-u", str(WRAP), "willikins-test"],
        env=env,
    )
    target = envs_dir / "willikins-test.json"
    for _ in range(40):
        if target.exists():
            break
        time.sleep(0.1)
    assert target.exists()

    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=5)
    # SIGKILL on the wrapper also kills its child; envs file is orphaned.
    assert target.exists(), "envs file should persist on SIGKILL"
```

```bash
python -m pytest kali/tests/test_wrap_claude.py -x 2>&1 | tail -15
```

Expected: FAIL (script missing).

- [ ] **Step 2: Implement `wrap-claude.py`**

Create `kali/scripts/wrap-claude.py`:

```python
#!/usr/bin/env python3
"""wrap-claude.py — supervisor around `claude remote-control` that records the
bridge env_id to a file we own, so an orphan reaper can clean up when claude
dies without invoking its own bridge:shutdown handler.

Usage:
  wrap-claude.py <session_name> [extra claude args...]

Environment:
  WILLIKINS_AGENT_DIR  — default ~/.willikins-agent (envs file lives here)
  CLAUDE_BIN_OVERRIDE  — alternate binary path, for tests
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ENV_RE = re.compile(r"env_[A-Za-z0-9_-]{6,}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: wrap-claude.py <session_name> [extra args]", file=sys.stderr)
        return 2
    session = sys.argv[1]
    extra = sys.argv[2:]
    agent_dir = Path(os.environ.get("WILLIKINS_AGENT_DIR", Path.home() / ".willikins-agent"))
    envs_dir = agent_dir / "envs"
    envs_dir.mkdir(parents=True, exist_ok=True)
    envs_file = envs_dir / f"{session}.json"

    claude_bin = os.environ.get("CLAUDE_BIN_OVERRIDE", "claude")
    if claude_bin == "claude":
        argv = ["claude", "remote-control", "--name", session, *extra]
    else:
        argv = [claude_bin]

    child = subprocess.Popen(
        argv,
        stdout=sys.stdout,
        stderr=subprocess.PIPE,
        stdin=sys.stdin,
        bufsize=1,
        text=True,
    )

    # Forward SIGTERM/SIGINT to child
    def forward(signum, _frame):
        if child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    # Tail stderr in a thread; write unchanged to our stderr; grep for env_id.
    def tail_stderr():
        assert child.stderr is not None
        seen_env = False
        for line in child.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            if seen_env:
                continue
            m = ENV_RE.search(line)
            if m:
                envs_file.write_text(json.dumps({
                    "env_id": m.group(0),
                    "pid": child.pid,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }))
                seen_env = True

    t = threading.Thread(target=tail_stderr, daemon=True)
    t.start()

    rc = child.wait()
    t.join(timeout=2)

    if rc == 0:
        try:
            envs_file.unlink()
        except FileNotFoundError:
            pass

    return rc


if __name__ == "__main__":
    sys.exit(main())
```

```bash
chmod +x kali/scripts/wrap-claude.py
python -m pytest kali/tests/test_wrap_claude.py -x 2>&1 | tail -10
```

Expected: both tests pass.

- [ ] **Step 3: Branch-B reaper variant**

Create `kali/scripts/reap-orphan-envs.sh` as in Task 3 Step 1, but replace the pointer discovery block with:

```bash
shopt -s nullglob
envs_files=( "$AGENT_DIR/envs"/*.json )
# and iterate envs_files rather than pointer files, reading from them
# the same env_id / pid fields.
```

All other logic (credentials, DELETE, backoff, status handling) is identical.

- [ ] **Step 4: Update session-manager spawn line**

In `kali/scripts/session-manager.sh`, replace line 54:

```bash
nohup bash -c "exec claude remote-control --name '$SESSION_NAME' < <(echo y)" \
  >> "/home/claude/.willikins-agent/session-${SESSION_NAME}.log" 2>&1 &
```

with:

```bash
nohup bash -c "exec python3 -u /opt/scripts/wrap-claude.py '$SESSION_NAME' < <(echo y)" \
  >> "/home/claude/.willikins-agent/session-${SESSION_NAME}.log" 2>&1 &
```

Also add the reaper invocation per Task 3 Step 3.

### Task 5: Open PR

- [ ] **Step 1: Verify all tests pass**

Branch A:

```bash
bash kali/tests/test_reap_orphan_envs.sh
python -m pytest kali/tests/ 2>&1 | tail -10
```

Branch B:

```bash
python -m pytest kali/tests/test_wrap_claude.py kali/tests/ 2>&1 | tail -10
bash kali/tests/test_reap_orphan_envs.sh  # if authored as bash for B too
```

Expected: all green.

- [ ] **Step 2: Commit and push**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images
git checkout -b feat/orphan-env-reaper
# Branch A:
git add kali/scripts/reap-orphan-envs.sh kali/scripts/session-manager.sh \
        kali/tests/test_reap_orphan_envs.sh \
        kali/docs/findings/2026-04-22-orphan-env-reaper.md
# Branch B additionally:
# git add kali/scripts/wrap-claude.py kali/tests/test_wrap_claude.py
git commit -m "feat(agent): orphan-env reaper for silent-reconnect phantoms"
git push -u origin feat/orphan-env-reaper
gh pr create --fill
```

---

## Phase 2: 48h soak [manual]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/31 -->

**Depends on:** Phase 1

### Task 1: Deploy

- [ ] **Step 1: Merge Phase 1 PR and build image**

```bash
gh pr merge --squash --delete-branch $(gh pr view feat/orphan-env-reaper --json number -q .number)
gh workflow run build.yml --repo derio-net/agent-images --ref main
# Wait for image to publish; note the new tag (ghcr.io/derio-net/secure-agent-kali:<sha>)
```

- [ ] **Step 2: Roll the pod on Frank**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/frank
# Update kali image tag in apps/secure-agent-pod/manifests/deployment.yaml
# Commit, push — ArgoCD auto-syncs. Or manually:
source .env
kubectl -n secure-agent-pod set image deploy/secure-agent-pod kali=ghcr.io/derio-net/secure-agent-kali:<new-sha>
kubectl -n secure-agent-pod rollout status deploy/secure-agent-pod --timeout=5m
```

- [ ] **Step 3: Capture baseline**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env
START_TS=$(date -u +%FT%T)
echo "$START_TS" > /tmp/reaper-soak-start.txt

kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  echo "=== reap log present? ==="
  ls -la ~/.willikins-agent/reap-orphan-envs.log 2>&1 || echo "not yet"
  echo "=== pointer files ==="
  find ~/.claude/projects -name bridge-pointer.json | wc -l
  echo "=== envs files (Branch B only) ==="
  ls ~/.willikins-agent/envs/ 2>/dev/null || echo "none"
  echo "=== session-manager log tail ==="
  tail -5 ~/.willikins-agent/session-manager.log
'
```

Manually count current phantom `willikins` environments in the claude.ai UI. Record as baseline.

### Task 2: Observe for 48h

- [ ] **Step 1: Checkpoint at T+8h**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env
kubectl -n secure-agent-pod exec deploy/secure-agent-pod -c kali -- bash -c '
  echo "=== stale-PID restarts ==="
  grep -c "stale PID" ~/.willikins-agent/session-manager.log || true
  echo "=== reaper invocations ==="
  grep -c "\[reap\]" ~/.willikins-agent/reap-orphan-envs.log || true
  echo "=== DELETE response breakdown ==="
  grep -oE "HTTP [0-9]{3}" ~/.willikins-agent/reap-orphan-envs.log | sort | uniq -c || true
  echo "=== live claude PIDs ==="
  pgrep -af "claude remote-control" | wc -l
'
kubectl -n secure-agent-pod describe pod -l app=secure-agent-pod | grep -E "OOMKilled|Last State|Restart" | head -20
```

Count phantoms in claude.ai UI. Record delta vs. baseline.

- [ ] **Step 2: Checkpoint at T+24h**

Re-run the T+8h commands. Any new OOMKill events? Any new stale-PID restarts? Does phantom count in claude.ai match the reaper's DELETE count?

- [ ] **Step 3: Checkpoint at T+48h**

Re-run once more. Record the final stratification:

- Total stale-PID restarts (session-manager log)
- Total reaper DELETE attempts (HTTP 2xx + 404 + 401 + 5xx + other)
- Net phantom-count delta in claude.ai
- OOMKill events from `kubectl describe`

### Task 3: Outcome note and follow-up decisions

- [ ] **Step 1: Post soak summary to agent-images#2**

```bash
gh issue comment 2 --repo derio-net/agent-images --body "$(cat <<'EOF'
## Orphan-env reaper — T+48h soak outcome

[baseline phantom count → final]
[stale-PID restarts in window / reaper DELETE counts by response code]
[OOMKill events stratified]
[any 401/403/5xx bugs discovered]

**Conclusion:** <net reduction achieved / residual gaps identified>

**Follow-ups filed:** <links or "none">
EOF
)"
```

- [ ] **Step 2: Trigger follow-up plans if needed**

Decision rules:
- **DELETEs succeeded but phantoms still accumulating** → log-scan to find the unclean-death path the reaper misses (e.g., a cwd change before crash invalidates the pointer location). Open a new plan.
- **401/403 on DELETE loops** → creds format drift; open a small fix plan.
- **No OOMKills in window but phantom count only fell by ~11 (silent-reconnect piece only)** → Plan 3 (vk-local memory profile) status unchanged, this plan is complete.
- **OOMKills fired and reaper caught them** → Plan 3 can later downgrade priority.
- **Zero stale-PID events in 48h** → reaper untested in production; extend soak by another 48h before closing.

- [ ] **Step 3: Mark plan status**

Edit the **Status:** header of this plan to `Deployed` (or `Complete` if the reaper was useful but uneventful). Update the **Status** column in the original spec's Implementation Plans table. Close the loop on the soak-followup issue if appropriate.
