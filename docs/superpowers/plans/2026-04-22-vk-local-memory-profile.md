# vk-local Memory Profiling Implementation Plan

> **For VK agents:** Use vk-execute to implement assigned phases.
> **For local execution:** Use subagent-driven-development or executing-plans.
> **For dispatch:** Use vk-dispatch to create Issues from this plan.

**Spec:** `docs/superpowers/specs/2026-04-18-persistent-agent-reliability-design.md`
**Status:** Not Started

**Goal:** Diagnose why the `vk-local` container in `secure-agent-pod` is consistently OOMKilled at its 2Gi limit (6× in ~48h observed during Phase 3 soak of the 2026-04-18 plan — Deviation D4), and produce a data-driven recommendation for one of: (a) raise the limit, (b) cap working-set in the binary, (c) identify and fix a leak.

**Context:** `vk-local` is a compiled Rust binary (`/usr/local/bin/vibe-kanban`, sourced from `ghcr.io/derio-net/vibe-kanban-build`) serving HTTP on :8081 inside `secure-agent-pod`. It shares a PVC with the `kali` container at `/home/claude`. The 2Gi limit was set in `derio-net/frank` `apps/secure-agent-pod/manifests/deployment.yaml:143` without profiling data — it was a guess based on initial idle footprint. OOMKill pattern observed in Phase 3 soak: ~1 kill per 8 hours, no correlation with kali restart events (kali had 0 restarts in the same window).

**Architecture:** This is an **investigation plan**, not a deployment. Output is a report under `kali/docs/findings/2026-04-22-vk-local-memory-profile.md` with:
- A time-series of RSS + `/proc/PID/status` fields across a representative window.
- Correlation with activity (HTTP request volume if accessible, kali tool-use bursts via audit log).
- Heap allocator stats if exposable (jemalloc, tokio task count if tokio-console wired).
- A decision: raise limit to N, or file a follow-up deploy plan against `derio-net/frank`, or an upstream fix against `ghcr.io/derio-net/vibe-kanban-build`.

**Tech Stack:** `/proc/PID/status`, `ps`, Prometheus (kube-state-metrics + node-exporter already scraped by frank's VictoriaMetrics), Grafana for ad-hoc dashboarding, optionally `jemalloc` stats via signal if the binary embeds it.

**Scope boundary:** This plan delivers a *report and decision*, not a fix. Implementation of whatever the report recommends is a separate plan (likely filed against `derio-net/frank` for a limit bump, or against `derio-net/agent-images` or the upstream fork for a code-level change). Do not ship a limit bump from within this plan — the whole point is to know whether that's even the right answer.

**Out of scope:**
- Kali-container memory behavior (already proven stable — 0 restarts at 32Gi limit).
- Network-side profiling of the VibeKanban relay (separate concern).
- Comparing `vk-local` to hosted vk.cluster.derio.net (different workload shape).

---

## Phase 1: Workload survey & tooling check [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/7 -->

**Depends on:** —

### Task 1: Characterize what vk-local actually runs

**Files:**
- Create: `kali/docs/findings/2026-04-22-vk-local-memory-profile.md` (scratch doc, filled incrementally)

- [x] **Step 1: Identify the vibe-kanban binary's vintage**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  bash -c 'ls -lh /usr/local/bin/vibe-kanban; file /usr/local/bin/vibe-kanban 2>/dev/null; /usr/local/bin/vibe-kanban --version 2>&1 || true'
```

Expected: a `ELF 64-bit LSB pie executable x86-64` with a stable size (~20-80 MB). Record SHA and mtime. If the binary is `statically linked` and `stripped`, jemalloc stats over signal won't work — adjust Phase 2 accordingly.

Note the image tag shown in `apps/secure-agent-pod/manifests/deployment.yaml:107` and correlate with the agent-images `vk-local/Dockerfile` `VK_FORK_SHA` build-arg to trace the upstream commit.

- [x] **Step 2: List the binary's linked libraries**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  bash -c 'ldd /usr/local/bin/vibe-kanban 2>&1 | head -20'
```

If `ldd` shows `libjemalloc.so.*` → the binary uses jemalloc and we can snapshot via `MALLOC_CONF=prof_dump_path:...` + `USR2` signal. If glibc malloc only → we're limited to RSS + `/proc/PID/status`.

- [x] **Step 3: Enumerate HTTP surface under load**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- \
  bash -c 'curl -s http://localhost:8081/api/health; echo; curl -s http://localhost:8081/api/ 2>/dev/null | head -50'
```

Goal: confirm the server is responsive and list any endpoints exposed. The server shouldn't be under heavy load in idle state — any steady growth in RSS from idle is a leak.

- [x] **Step 4: Draft the findings doc skeleton**

Create `kali/docs/findings/2026-04-22-vk-local-memory-profile.md` with:

```markdown
# vk-local Memory Profile — Findings

## Context

Deviation D4 of `docs/superpowers/plans/2026-04-18-persistent-agent-reliability.md` flagged 6 OOMKills in ~48h at the 2Gi limit. This doc is the per-task scratchpad for the Phase 3 follow-up plan `2026-04-22-vk-local-memory-profile.md`.

## Binary

- Image: <sha>
- Upstream commit: <VK_FORK_SHA>
- Size: <MB>
- Allocator: <jemalloc|glibc>
- Stripped: <yes|no>

## HTTP surface

[Endpoints + purpose]

## Observation window

- Start: <UTC ISO>
- End: <UTC ISO>
- OOMKills observed: <N>
- Pre-kill RSS peak: <MB>
- Idle RSS baseline: <MB>

## Activity correlation

[Table of OOMKill timestamps vs kali audit log bursts vs VK HTTP request counts]

## Decision

One of:
- **A (raise limit):** recommended limit = <N> Gi, justification = <peak + margin>. Follow-up deploy plan against derio-net/frank.
- **B (upstream cap):** working-set is unbounded under workload X. File upstream issue against ghcr.io/derio-net/vibe-kanban-build.
- **C (leak):** heap grows linearly even at idle by <rate>/h. File code-level fix PR against fork repo.

Chosen: <A|B|C>. Rationale: <para>.
```

Do NOT commit this file yet — it's filled across Phases 1–3.

### Task 2: Verify Prometheus + Grafana instrumentation

**Files:**
- None (read-only verification).

- [x] **Step 1: Confirm kube-state-metrics tracks the vk-local container**

From the Frank control host:

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n monitoring deploy/vmselect-victoria -- \
  wget -qO- 'http://localhost:8481/select/0/prometheus/api/v1/query?query=container_memory_working_set_bytes{namespace="secure-agent-pod",container="vk-local"}' | head -30
```

Expected: JSON with `result` array containing one entry and a recent `value` (MB range).

- [x] **Step 2: Confirm OOMKill events are tracked**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n monitoring deploy/vmselect-victoria -- \
  wget -qO- 'http://localhost:8481/select/0/prometheus/api/v1/query?query=kube_pod_container_status_last_terminated_reason{namespace="secure-agent-pod",container="vk-local",reason="OOMKilled"}' | head -30
```

Expected: at least one entry with a timestamp matching a known OOMKill. If the metric doesn't exist, fall back to `kubectl get events -n secure-agent-pod` correlation.

- [x] **Step 3: Check if node-exporter tracks cgroup-level memory for this container**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n monitoring deploy/vmselect-victoria -- \
  wget -qO- 'http://localhost:8481/select/0/prometheus/api/v1/query?query=container_memory_rss{namespace="secure-agent-pod",container="vk-local"}' | head -30
```

Expected: RSS in bytes for the current process. If missing, use the `container_memory_working_set_bytes` series from Step 1 as the primary signal (working_set ≈ RSS + active file cache for cgroup v2).

---

## Phase 2: Observation window [manual]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/8 -->

**Depends on:** Phase 1

### Task 1: Run the 24h data collection

**Files:**
- Modify: `kali/docs/findings/2026-04-22-vk-local-memory-profile.md` (append data over time)

- [ ] **Step 1: Record pre-window snapshot**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  START_TS=$(date -u +%FT%TZ) && \
  echo "Window start: $START_TS" && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  bash -c 'cat /proc/1/status | grep -E "^(VmRSS|VmSize|VmPeak|VmHWM|RssAnon|RssFile|Threads)"; echo; cat /proc/1/smaps_rollup 2>/dev/null | head -20'
```

Record `VmRSS` (current resident), `VmHWM` (high-water mark), `Threads`. Append to findings doc.

- [ ] **Step 2: Set up a lightweight in-pod sampler**

The pod has no persistent sidecar for this, so run a one-shot ad-hoc sampler that writes to the PVC for later retrieval:

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- \
  bash -c 'cat > /home/claude/.willikins-agent/vk-local-memsample.sh <<'"'"'EOF'"'"'
#!/bin/bash
# Ad-hoc RSS sampler — runs from kali container, samples vk-local process via shared PID namespace check.
OUT="/home/claude/.willikins-agent/vk-local-memsample.tsv"
if [[ ! -f "$OUT" ]]; then
  echo -e "ts_utc\tpid\trss_kb\tvsize_kb\tthreads" > "$OUT"
fi
# We are in kali; kubectl exec to vk-local peer requires shared PID namespace — not default.
# Instead, read from the cgroup via the kubelet exposed path.
# Fallback: rely on VictoriaMetrics scrape (see Phase 1 Task 2).
ts=$(date -u +%FT%TZ)
# Use container_memory stats via /sys if mounted — otherwise emit a ping marker.
echo -e "${ts}\t-\t-\t-\t-" >> "$OUT"
EOF
chmod +x /home/claude/.willikins-agent/vk-local-memsample.sh'
```

**Important:** kali and vk-local are separate containers in the same pod but do NOT share a PID namespace by default (no `shareProcessNamespace: true` on the pod spec). So kali can't `ps` vk-local's process directly. The reliable path is to sample from vk-local directly via `kubectl exec` at an interval, OR use the Prometheus series already scraping the container.

Given that, **skip the in-pod sampler and rely on VictoriaMetrics** for continuous sampling. Use the sampler only to mark experiment boundaries.

- [ ] **Step 3: Take 6 manual RSS snapshots over 24h (every 4h)**

From the Frank control host, at T+0, T+4h, T+8h, T+12h, T+16h, T+20h, T+24h:

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  TS=$(date -u +%FT%TZ) && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  bash -c "cat /proc/1/status | grep -E '^(VmRSS|VmHWM|Threads)' | awk -v ts=\"$TS\" '{print ts, \$0}'"
```

Append each snapshot to the findings doc under a "Manual RSS snapshots" table. If an OOMKill happens mid-window, note the timestamp and the pre-kill RSS (visible in kubectl describe → Last State → Finished).

- [ ] **Step 4: At T+24h, export the VictoriaMetrics time-series**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  START=$(date -u -v-24H +%s) && \
  END=$(date -u +%s) && \
  kubectl exec -n monitoring deploy/vmselect-victoria -- \
  wget -qO- "http://localhost:8481/select/0/prometheus/api/v1/query_range?query=container_memory_working_set_bytes{namespace=\"secure-agent-pod\",container=\"vk-local\"}&start=${START}&end=${END}&step=60s" \
  > /tmp/vk-local-wss-24h.json
  wc -l /tmp/vk-local-wss-24h.json
  jq '.data.result[0].values | length' /tmp/vk-local-wss-24h.json
```

Expected: one series with 1440 data points (24h × 60 min). If the series has gaps (< 1200 pts), note this — OOMKills cause scrape gaps.

- [ ] **Step 5: Correlate with OOMKills**

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl get events -n secure-agent-pod --field-selector reason=Killing -o json 2>&1 | \
  jq -r '.items[] | select(.message | test("OOM|memory")) | "\(.lastTimestamp) \(.message)"'
```

Append OOMKill timestamps to the findings doc. Cross-reference with pre-kill RSS values — each OOM should have a peak within the scrape window just prior.

### Task 2: Activity correlation

**Files:**
- Modify: `kali/docs/findings/2026-04-22-vk-local-memory-profile.md`

- [ ] **Step 1: Count kali audit log entries in the window**

The kali audit log (`~/.willikins-agent/audit.jsonl` + daily archives under `audit-archive/`) tracks tool-use bursts which may correlate with VK HTTP load.

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- \
  bash -c 'ls -lh ~/.willikins-agent/audit-archive/ && wc -l ~/.willikins-agent/audit-archive/audit-$(date -u +%Y%m%d).jsonl'
```

Append line count + size to the findings doc for the observation day.

- [ ] **Step 2: Hour-bucket audit activity and RSS**

Write a short Python snippet (on the Frank host, not in the pod) that:
1. Reads the 24h VictoriaMetrics export from Phase 2 Task 1 Step 4.
2. Computes max RSS per hour.
3. Correlates with hourly audit-line counts (from the downloaded audit archive).
4. Emits a CSV with columns `hour, max_rss_mb, audit_lines, oomkill_in_hour`.

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl cp secure-agent-pod/$(kubectl get pod -n secure-agent-pod -l app=secure-agent-pod -o jsonpath='{.items[0].metadata.name}'):/home/claude/.willikins-agent/audit-archive/audit-$(date -u +%Y%m%d).jsonl /tmp/audit-today.jsonl -c kali
  ls -lh /tmp/audit-today.jsonl
```

Run a correlation script locally (script body flexible; just load both time-series and emit the CSV). Append summary table to findings doc.

If hour-level correlation is strong (r > 0.5): memory scales with workload → bump limit or cap. If weak: likely a leak.

---

## Phase 3: Analysis & recommendation [agentic]
<!-- Tracking: https://github.com/derio-net/agent-images/issues/9 -->

**Depends on:** Phase 2

### Task 1: Classify the memory pattern

**Files:**
- Modify: `kali/docs/findings/2026-04-22-vk-local-memory-profile.md`

- [ ] **Step 1: Plot RSS over the window**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/frank
# If uv-venv is available:
.venv/bin/python -c "
import json, sys
data = json.load(open('/tmp/vk-local-wss-24h.json'))
pts = data['data']['result'][0]['values']
# values are [[ts_unix, 'bytes_as_string'], ...]
import csv
with open('/tmp/vk-local-rss.csv', 'w') as f:
    w = csv.writer(f)
    w.writerow(['ts_unix', 'rss_bytes', 'rss_mb'])
    for ts, v in pts:
        b = float(v)
        w.writerow([ts, b, round(b/1024/1024, 1)])
print('Wrote /tmp/vk-local-rss.csv with', len(pts), 'rows')
" 2>&1
```

Inspect the CSV. Classify the pattern:
- **Sawtooth, reset at OOMKill:** standard "grows under load, killed, restarts" → recommendation A (raise limit) or B (upstream cap).
- **Monotonic growth at idle:** leak → recommendation C (code-level fix).
- **Stable baseline + large transient spikes:** workload-driven burst → bump limit with margin = max(spike) + 25%.

- [ ] **Step 2: Compute the recommendation number**

If Recommendation A:
```bash
# Peak RSS observed in window + 25% safety margin
.venv/bin/python -c "
import csv
rows = list(csv.DictReader(open('/tmp/vk-local-rss.csv')))
peak_mb = max(float(r['rss_mb']) for r in rows)
rec_mib = int(peak_mb * 1.25)
# Round up to nearest 256 MiB for K8s limit hygiene
rec_mib = ((rec_mib + 255) // 256) * 256
print(f'Peak RSS: {peak_mb:.0f} MiB, recommended limit: {rec_mib} MiB ({rec_mib/1024:.1f} Gi)')
"
```

Expected output: a concrete number like "Peak RSS: 1850 MiB, recommended limit: 2560 MiB (2.5 Gi)" — or evidence that even 4 Gi would be insufficient (in which case escalate to Recommendation B or C).

### Task 2: Write the report & commit

**Files:**
- Modify: `kali/docs/findings/2026-04-22-vk-local-memory-profile.md`

- [ ] **Step 1: Fill all empty sections of the findings doc**

By this point every template section (Binary, HTTP surface, Observation window, Activity correlation, Decision) should have data. Write the narrative: what was observed, what rules it out, what the recommendation is, and the confidence level.

- [ ] **Step 2: Commit on a feature branch**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images
git checkout -b investigation/vk-local-memory-profile
git add kali/docs/findings/2026-04-22-vk-local-memory-profile.md \
        docs/superpowers/plans/2026-04-22-vk-local-memory-profile.md
git status
git commit -m "docs: vk-local memory profile findings (Phase 3 follow-up of 2026-04-18)"
```

- [ ] **Step 3: Open PR with the recommendation summary in the body**

```bash
gh pr create --title "docs: vk-local memory profile — <A|B|C> decision" \
  --body "$(cat <<'EOF'
## Summary

Investigation report closing out Deviation D4 from `2026-04-18-persistent-agent-reliability.md`. Soak observed 6 OOMKills in 48h at 2Gi; this profile ran a 24h observation window to characterize the pattern and recommend a fix.

**Decision:** <A|B|C>

- **A:** raise `vk-local` memory limit to <N> Gi in `derio-net/frank` `apps/secure-agent-pod/manifests/deployment.yaml:143`.
- **B:** upstream issue against the vibe-kanban fork — working-set is unbounded under workload <X>.
- **C:** leak — file code-level PR against fork repo; limit bump is a band-aid.

## Data

- Binary: <sha>, <size> MiB, allocator = <jemalloc|glibc>
- Observation window: <start UTC> → <end UTC>
- OOMKills in window: <N>
- Idle RSS baseline: <MB>
- Peak RSS pre-kill: <MB>
- Workload correlation (r vs audit lines/hour): <value>

## Follow-up

- [ ] Implementation plan for the chosen recommendation (separate PR, separate repo)
- [ ] Reference this report from `2026-04-18-persistent-agent-reliability.md` Deviations section

Refs: `derio-net/agent-images#2` (Phase 3 T+48h comment), plan `docs/superpowers/plans/2026-04-22-vk-local-memory-profile.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Task 3: Close the loop on the umbrella issue

**Files:**
- None (GH comment, no repo edits).

- [ ] **Step 1: Comment on `derio-net/agent-images#2`**

Once the PR is merged:

```bash
gh issue comment 2 --repo derio-net/agent-images --body "$(cat <<'EOF'
Phase 3 follow-up plan `2026-04-22-vk-local-memory-profile.md` merged. Findings doc: `kali/docs/findings/2026-04-22-vk-local-memory-profile.md`. Decision: <A|B|C>. Implementation of the recommendation will be a separate plan.
EOF
)"
```

---

## Status updates

- 2026-04-22: Plan written alongside `2026-04-22-vk-bridge-warn-patterns.md` during the Phase 3 T+48h checkpoint of the 2026-04-18 plan. Investigation-only — the fix it recommends lives in whichever repo the finding indicates.
