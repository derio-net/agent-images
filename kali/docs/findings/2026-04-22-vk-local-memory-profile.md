# vk-local Memory Profile — Findings

## Context

Deviation D4 of `docs/superpowers/plans/2026-04-18-persistent-agent-reliability-design.md` flagged 6 OOMKills in ~48h at the 2Gi limit. This doc is the cross-phase scratchpad for the follow-up plan `docs/superpowers/plans/2026-04-22-vk-local-memory-profile.md`.

**Status:** Phase 1, Phase 2, and Phase 3 complete. **Decision: A (raise limit to 8 Gi, immediate) + B housekeeping (npm cache prune + worktree TTL) + B1 follow-up (max-concurrent-sessions cap).** Implementation in separate deploy plan against `derio-net/frank`.

---

## Phase 1 — Workload survey & tooling check

Data collected 2026-04-23 by the Phase 1 agent. Environment: `frank` cluster, pod `secure-agent-pod-68f7bb7896-2nn6c` on node `gpu-1`, restart count 8, last OOMKill 2026-04-23 06:07:15 UTC (8h 26m after prior start).

### Binary

- **Image (pod spec):** `ghcr.io/derio-net/vk-local:ed62d429d523515a1433b17450f2ffe2157b0ffb`
- **Image ID (actual, running):** `ghcr.io/derio-net/vk-local@sha256:3c85b325cc535f425301a419d593b3498d31e37e10ed9c02668209eb55067104`
- **Upstream `VK_FORK_SHA`:** not embedded in the binary; must be read from the `vk-local` image build metadata. The image tag in the Deployment (`ed62d429…`) is the `agent-images` repo SHA that triggered the build, not `VK_FORK_SHA`.
- **On-disk path:** `/usr/local/bin/vibe-kanban`
- **On-disk size:** 139,643,680 bytes (≈ 133 MiB)
- **mtime:** 2026-04-18 06:40:55 UTC
- **SHA-256:** `d3bbcd70b187e757f41426db6915886e8e967640ab958efa3b88b5147679b9bf`
- **ELF:** dynamically linked, `linux-x86-64` (ELF magic `\x7FELF` confirmed; `file`/`readelf` not installed in the image).
- **Reported server version (`/api/info`):** `0.1.42`, config version `v8`.
- **Allocator:** **glibc malloc.** `ldd` shows only `libc.so.6`, `libgcc_s.so.1`, `libm.so.6`, `linux-vdso.so.1`, `ld-linux-x86-64.so.2` — no `libjemalloc`. This rules out the jemalloc `USR2` profiling path sketched in Phase 2. Heap analysis must fall back to RSS + `/proc/PID/status` + cgroup stats.
- **Stripped:** not confirmed (no `readelf` / `file` in the image). Size ≈ 133 MiB is *suggestive* of debug symbols retained or large panic-backtrace / tracing-instrumentation footprint, but this is a hypothesis, not a finding — Phase 2 or a follow-up can confirm via `readelf -S` from a debugger sidecar.
- **CLI flags:** `--version` is not wired up — it falls through to server startup and then crashes with `AddrInUse` because the main instance is already bound. Treat the binary as having no out-of-band version flag.

### Process shape (unexpected — critical for Phase 2 interpretation)

The `vk-local` container does **not** run a single Rust process. At the time of sampling, the cgroup contained a process tree with Claude Code as a child:

```
PID  PPID    RSS COMMAND
  1     0   1300 tini
  7     1 150188 vibe-kanban           <- Rust server, PID 7
1513    7 389632 claude                <- Claude Code CLI spawned by vibe-kanban
1535 1513  81664 npm                   <- child of claude (e.g. @upstash/... MCP)
1587 1586  85912 node
24245 ...   54492 kubectl              <- bash/kubectl invoked by claude
...
TOTAL: 760 MiB RSS (one active claude session)
```

cgroup `memory.current` at the same sample: **791,285,760 B (755 MiB)** — matches the sum.  
cgroup `memory.peak` since container start (14h window): **1,367,040,000 B (1,304 MiB)**.  
cgroup `memory.max` (limit): **2,147,483,648 B (2 Gi)**.

vibe-kanban itself (PID 7): `VmRSS ≈ 147 MiB`, `Pss_Anon ≈ 104 MiB` (private dirty heap), the rest is file-backed (binary text + libs). That is small and plausible.

**Implication for the plan's decision tree:** an "idle vk-local" sample is a misleading baseline. The cgroup fills with **`claude` CLI + `npm`/`node` + `kubectl` subprocesses** that `vibe-kanban` forks per task (local executions). Each active claude session adds on the order of **0.4–0.6 GiB** to the cgroup. 3–4 concurrent sessions trivially reach the 2 GiB cap. Phase 3 must decide between (A) raising the cgroup limit to cover the expected concurrency, (B) capping the concurrency / forcing those sessions out-of-process (no longer children of vk-local's cgroup), or (C) only if per-process RSS grows unbounded within a single session — looking for leaks inside one of the child processes, not vibe-kanban itself.

### HTTP surface

Real endpoints (routed, non-SPA):

| Path            | Method | Status | Content-Type             | Notes                                    |
|-----------------|--------|--------|--------------------------|------------------------------------------|
| `/api/health`   | GET    | 200    | `application/json`       | Liveness + readiness probe target.       |
| `/api/info`     | GET    | 200    | `application/json`       | Exposes `version` + `config`.            |
| `/api/config`   | GET    | 405    | —                        | Exists (POST-only likely).               |
| `/api/events`   | GET    | 200    | `text/event-stream`      | Live SSE of workspace JSON-patch events. |

All other `/api/*` and `/metrics`/`/api/metrics` paths return **SPA fallback HTML** (the Vite build's `index.html`), which is why naïve endpoint enumeration returned 200/text-html for them. **There is no Prometheus-style `/metrics` endpoint on the vk-local binary itself**; per-request/per-session instrumentation is not available via HTTP.

Probes configured in the Deployment:

- Liveness: `http-get /api/health` delay=30s, timeout=1s, period=30s, failure=3
- Readiness: `http-get /api/health` delay=10s, timeout=1s, period=10s, failure=3

### Tooling check — summary

| Tool / metric                                                   | Available? | Notes                                                                                                              |
|-----------------------------------------------------------------|-----------:|--------------------------------------------------------------------------------------------------------------------|
| `kube_pod_container_status_last_terminated_reason="OOMKilled"`  | ✅          | Confirmed for `secure-agent-pod / vk-local`; value `1`.                                                            |
| `kube_pod_container_status_restarts_total`                      | ✅          | Current: **8**. Last 24h: **+2**. Last 7d across rollouts: aggregate **~25** across 5 pod-replica generations.     |
| `kube_pod_container_resource_limits`                            | ✅          | `memory = 2147483648` (2 Gi), `resource=cpu/memory` labels present.                                                |
| `container_memory_working_set_bytes{container="vk-local"}`      | ❌          | **Empty.** cadvisor is scraped only for nodes `raspi-1` and `raspi-2`; `gpu-1` (where vk-local runs) is not.       |
| `container_memory_rss{container="vk-local"}`                    | ❌          | Same gap — cadvisor not scraping `gpu-1`.                                                                          |
| `container_oom_events_total{container="vk-local"}`              | ❌          | Same gap.                                                                                                          |
| `kubectl top pod`                                                | ❌          | `error: Metrics API not available` — metrics-server is not installed on the `frank` cluster.                       |
| `jemalloc` heap profile via `USR2`                               | ❌          | Binary does not link jemalloc.                                                                                     |
| `/proc/PID/status`, `/sys/fs/cgroup/memory.*`                    | ✅          | Usable via `kubectl exec -c vk-local`. This is the only available continuous signal.                               |
| Namespace events (`kubectl get events`)                          | ⚠️         | Default 1h retention; not useful for a 24h window unless we re-poll continuously.                                  |

**Phase 2 impact:** the plan's Phase 2 Task 1 Steps 4–5 rely on `container_memory_working_set_bytes` from VictoriaMetrics for a continuous 1-minute RSS scrape. **That path is unavailable.** Phase 2 must be adjusted to:

1. **Primary sampler** — a 60-second loop that runs the following three commands via `kubectl exec` (driver can be the Frank control host or a long-running kali-container background job):

    ```bash
    # (1) Per-process snapshot of the vk-local cgroup — find the vibe-kanban PID
    #     dynamically because it is not always PID 7 after restarts.
    kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
      ps -eo pid,ppid,rss,vsz,comm --sort=-rss

    # (2) vibe-kanban process detail (substitute the PID discovered in (1))
    kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
      bash -c 'grep -E "^(VmPeak|VmSize|VmHWM|VmRSS|RssAnon|RssFile|VmData|Threads)" /proc/$PID/status'

    # (3) cgroup-level current / peak / limit — the ground truth for the 2 GiB cap
    kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
      bash -c 'cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.max'
    ```

    Store one row per sample with per-child RSS — the process tree is the signal, not any single PID.

2. **OOM correlation** — poll `kube_pod_container_status_last_terminated_timestamp` and `_reason` from VictoriaMetrics every minute (this *is* scraped for this container). The driver needs in-cluster reachability of `http://vmsingle-victoria-metrics-victoria-metrics-k8s-stack.monitoring.svc:8428` *or* a `kubectl exec` hop through a pod that does.

3. **Gap-filler for OOMKill events** — `kubectl exec`-based polling drops samples during restarts, so when an OOMKill lands mid-window capture the pre-kill number from `kubectl describe pod -n secure-agent-pod deploy/secure-agent-pod -c vk-local` (Last State → Finished block) to avoid a blind spot.

4. **Out-of-scope escalation** — fixing the cadvisor scrape coverage for `gpu-1` is a separate deploy-plan item against `derio-net/frank`; do not do it from this plan, but file a follow-up Issue so the gap doesn't get lost.

---

## Phase 2 — Observation window (pending)

### Observation window

- Start: 2026-04-26T09:27:28Z
- End: 2026-04-27T04:34:01Z (effectively, see "Window disruption" below; T+19h is the last clean snapshot in this attempt)
- OOMKills observed (in window): **0** (no in-window OOM signature on the cgroup, no pod-level OOMKilled state confirmed for this window — though `kubectl describe` was not captured at the rollout boundary, so this is "no positive evidence" rather than "verified absence")
- OOMKills observed (pre-window, captured for context): 1 at 2026-04-24T20:30:33Z (the event that motivated executing this plan)
- Pre-kill memory.peak: 2,147,487,744 B (2 Gi + one 4 KiB page — textbook cgroup OOM signature)
- Idle cgroup.current baseline (no active claude session): **~813 MiB** (T+0; updated from Phase 1's "vibe-kanban-only" misread — cgroup retains file cache, threads, slab even with zero children)
- Steady-state cgroup.current (1 active claude): ~755 MiB (single-sample, from Phase 1) — note this is *lower* than the new idle baseline because the Phase 1 sample didn't include retained cache from a previous session
- Post-rollout idle baseline: **~118 MiB** (T+11.5h and T+19h; new container instance, ~7.5h stable). Order-of-magnitude lower than the pre-rollout idle baseline of 813 MiB — strongly suggests retained file cache / slab / heap state from prior workload was the bulk of the pre-rollout idle, not steady-state requirement.

### Window disruption

`derio-net/agent-images@eb6ae08` (`feat(kali): add tmux + mosh for persistent shell sessions`, authored 2026-04-26T14:05:47Z = T+4h 38m) bumped `kali/Dockerfile`. The image rebuild + Deployment rollout rolled both containers in `secure-agent-pod` together (single-Deployment multi-container pods restart all containers on rollout). **This invalidates the original 24h continuity assumption** — the container we sampled at T+11.5h and T+19h is *not* the same instance as at T+0/T+0:22m. The pre-rollout window provided 22 minutes of usable observation; the post-rollout window provided ~7.5h ending at T+19h.

The right move for a clean Phase 2 retake is to start a new 24h window from the post-rollout container's start time. Phase 3's decision should not rely on this window's correlation analysis; instead it can use the structural findings (Phase 1 process tree + the post-rollout idle baseline of ~118 MiB) to make a conservative recommendation.

### Sampler design (Step 2)

The plan-as-written collapses Step 2 to "skip the in-pod sampler and rely on VictoriaMetrics" — but Phase 1 found VM has no cadvisor scrape for `gpu-1` (the node `secure-agent-pod` runs on). The Phase 1 redirect (Phase 2 impact section above) specified a 60-second `kubectl exec` polling sampler as the primary signal.

**Attempted continuous sampler (T+0:22m):** A Mac-local `launchd` job calling a single-shot script every 60s was prepared (script body below; plist at `~/Library/LaunchAgents/local.derionet.vk-local-memprofile.plist`). The harness guardrail blocked `launchctl bootstrap` for that job because automating recurring `kubectl exec` against a production-namespace pod requires explicit operator authorization. **Decision: do not run an unattended daemon. Fall back to the plan's manual 4h cadence (Step 3).** The script + plist remain on the Frank control host so the operator can authorize and load them later if desired.

**Sampler script** (`/Users/derio/.local/bin/vk-local-memprofile-sample.sh`): one-shot, idempotent, appends one TSV row to `/tmp/vk-memprofile/vk-local-memprofile.tsv`. Equivalent inline form for the manual cadence:

```bash
cd /Users/derio/Docs/projects/DERIO_NET/frank/ && source .env && \
  TS=$(date -u +%FT%TZ) && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local --request-timeout=15s -- bash -c '
PID=$(pgrep -x vibe-kanban | head -1)
[[ -n "$PID" ]] && {
  VK_RSS=$(awk "/^VmRSS:/ {print \$2}" /proc/$PID/status)
  VK_HWM=$(awk "/^VmHWM:/ {print \$2}" /proc/$PID/status)
  VK_TH=$(awk "/^Threads:/ {print \$2}" /proc/$PID/status)
} || { PID=- VK_RSS=- VK_HWM=- VK_TH=-; }
CG_CUR=$(cat /sys/fs/cgroup/memory.current)
CG_PEAK=$(cat /sys/fs/cgroup/memory.peak)
CG_MAX=$(cat /sys/fs/cgroup/memory.max)
ACTIVE=$(ps -eo comm --no-headers | grep -cE "^(claude|node|npm|kubectl)$") || ACTIVE=0
TOP=$(ps -eo pid,rss,comm --no-headers --sort=-rss | head -8 | awk "{printf \"%s:%s/%s,\",\$3,\$2,\$1}")
printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" "$PID" "$VK_RSS" "$VK_HWM" "$VK_TH" "$CG_CUR" "$CG_PEAK" "$CG_MAX" "$ACTIVE" "$TOP"
' | awk -v ts="$TS" '{print ts"\t"$0}'
```

`active_children` counts claude/node/npm/kubectl processes inside the vk-local cgroup at sample time. `top_rss` lists the eight RSS-heaviest processes as `comm:rss_kb/pid,...` (own sampler bash/awk/ps appear in the trail and are signal noise — discount them).

### Manual RSS snapshots (T+0, T+4h, T+8h, T+12h, T+16h, T+20h, T+24h)

| ts_utc                | VmRSS (vibe-kanban) | VmHWM     | Threads | cgroup.current | cgroup.peak    | active_children | notes                                                       |
|-----------------------|--------------------:|----------:|--------:|---------------:|---------------:|----------------:|-------------------------------------------------------------|
| 2026-04-26T09:27:28Z  | 190,000 kB          | 190,000 kB| 76      | 813 MiB        | 2 GiB + 4 KiB  | 0               | T+0 baseline; no active claude session; peak = pre-window OOM (24h ago) |
| 2026-04-26T09:49:35Z  | 190,000 kB          | 190,000 kB| 76      | 813.6 MiB      | 2 GiB + 4 KiB  | 0               | T+0:22m sanity check (sampler-script verification); ~0.6 MiB drift over 22m = ~1.6 MiB/h idle |
| 2026-04-26T21:00:17Z  | 80,556 kB           | 80,556 kB | 93      | 118.3 MiB      | 773 MiB        | 0               | T+11.5h. cgroup.peak dropped from 2 GiB+4 KiB to 773 MiB → vk-local restarted between T+0:22m and now. **Initial reading was "OOMKill mid-window" — corrected after seeing main: commit `eb6ae08 feat(kali): add tmux + mosh` (authored 2026-04-26T14:05:47Z = T+4h 38m) bumped the kali Dockerfile, forcing a Deployment rollout that rolled both pod containers. The peak reset is from that rollout, not an in-window OOMKill.** Without `kubectl describe pod` Last State data captured at the time, the kill-vs-rollout distinction is now retroactively probabilistic — but the timing alignment plus the absence of stress signals in the post-rollout cgroup (current 118 MiB at peak 773 MiB, no thrash) makes the rollout interpretation strongly more likely. |
| 2026-04-27T04:34:01Z  | 74,724 kB           | 74,724 kB | 112     | 118.9 MiB      | 784 MiB        | 0               | T+19h. Same container instance as T+11.5h (peak only +11 MiB over 7.5h). cgroup.current essentially flat (118.3 → 118.9 MiB). Threads still creeping (93 → 112 over 7.5h ≈ +2.5 threads/h). cgroup.max unchanged at 2 GiB — confirming the bump was the kali tmux/mosh Dockerfile change, **not** a memory-limit raise. Post-rollout container has been stable ~7.5h with zero observed OOMKills in this window. |
|                       |                     |           |         |                |                |                 |                                                             |

### Activity correlation

- Audit log lines per hour (kali `~/.willikins-agent/audit-archive/audit-YYYYMMDD.jsonl`):
- Claude session spawn count per hour (derived from `ps` sampler):
- Correlation (r) between hourly peak cgroup.current and audit lines/hour:

---

## Phase 2 retake (post-rollout window)

The original Phase 2 window (anchor 2026-04-26T09:27:28Z) was disrupted at T+4h 38m by the `agent-images@eb6ae08` (`feat(kali): add tmux + mosh`) Deployment rollout, which rolled both pod containers and reset `cgroup.peak`. PR #12 captured the disrupted observations; PR #13 documented the correction. This retake re-runs Phase 2 cleanly against the post-rollout `vk-local` container instance.

- **Anchor (T+0_retake):** 2026-04-27T04:48:34Z (`vk-local` container `startedAt`)
- **Pod / image:** `secure-agent-pod-b6b9bcd5d-jmc7n` running `ghcr.io/derio-net/vk-local:a90c6c16f332d6c9c22dea7bfa05a27e6272fa0f` (kali/vk-local rollout from agent-images main)
- **Baseline restartCount:** 1 (single OOMKill at 2026-04-27T04:48:33Z that prompted the current container start; the new container is still at restartCount=1 — any *increase* during the retake window is an in-window restart)
- **Window end:** T+24h_retake = 2026-04-28T04:48:34Z
- **Sampling cadence:** manual T+0 row + supercronic-driven `vk-snap.sh` fires at T+4h, T+8h, T+12h, T+16h, T+20h, T+24h (cron `48 */4 * * *` — minute aligned to anchor). Snapshot script writes from kali, commits to this PR's branch via the credential helper. Plain bash, no Claude wrapper, so its own activity is bounded to known cron-fire timestamps.

### Manual RSS snapshots (T+0, T+4h, T+8h, T+12h, T+16h, T+20h, T+24h)

| ts_utc                | VmRSS (vibe-kanban) | VmHWM     | Threads | cgroup.current | cgroup.peak    | active_children | notes                                                       |
|-----------------------|--------------------:|----------:|--------:|---------------:|---------------:|----------------:|-------------------------------------------------------------|
| 2026-04-27T04:55:15Z  | 131,284 kB          | 131,284 kB| 135     | 733 MiB        | 1.82 GiB       | 3               | T+0 manual baseline (container 6m41s old). PID 7. **Note:** cgroup.peak already 1.82 GiB despite young container — driven by the active claude session (this very routine + workload spike from the OOMKill@04:48:33Z that birthed this container). top-by-RSS: claude=288 MiB, vibe-kanban=128 MiB, npm=89 MiB, node=87 MiB, kubectl=55 MiB. |
| 2026-04-27T05:27:00Z  | 156,524 kB          | 156,524 kB| 126     | 473 MiB        | 1.82 GiB       | 0               | T+1h cron snapshot (pod `secure-agent-pod-b6b9bcd5d-jmc7n`). active_children=0 — the T+0 setup-session exited; vibe-kanban itself + slab + kernel only. cgroup.peak unchanged (1.82 GiB high-watermark from T+0's setup workload still standing). VmRSS up 25 MiB (131k → 156k) over 32m suggests post-startup vibe-kanban warmup, not steady-state drift. *(Backfilled from `~/.willikins-agent/vk-snap.log` — the cron-fired script captured the sample but its `git checkout` failed against the worktree-blocked `/home/claude/repos/agent-images` clone; vk-snap.sh was subsequently re-pointed to a dedicated PVC clone at `~/.willikins-agent/vk-snap-clone`.)* |
| 2026-04-27T09:27:00Z  | 163,724 kB          | 163,724 kB| 119     | 479 MiB        | 1.82 GiB       | 0               | T+5h cron snapshot (same pod). cgroup.current essentially flat (473 → 479 MiB over 4h ≈ +1.5 MiB/h drift). cgroup.peak unchanged. Threads slightly down (126 → 119). vibe-kanban RSS still creeping up (+7 MiB over 4h ≈ +1.75 MiB/h). *(Backfilled from log; same git-checkout failure as T+1h.)* |
| 2026-04-27T13:40:36Z  | _(pod replaced — no sample)_ | — | — | — | — | — | **Disruption.** Pod `secure-agent-pod-b6b9bcd5d-jmc7n` deleted; new pod `secure-agent-pod-69677554b6-2xg7j` created at this timestamp. Driver: `agent-images@dc414b4` (PR #13 merge, "vk-local memprofile T+19h post-rollout sample + corrected mid-window narrative") triggered an image rebuild → rolling Deployment update. New `vk-local` image: `ghcr.io/derio-net/vk-local:dc414b4b6c3cd1b8f8ecb27fa515aed6e9f170cf`. **NOT an OOMKill** — the OLD pod's cgroup.peak was 1.82 GiB at the last sample (well below the 2 GiB cap) and the rollout cause is documented. Per the operator's invariant, the window is NOT re-anchored — sampling continues from T+0_retake = 2026-04-27T04:48:34Z, with the disruption logged. New pod's `vk-local` container `restartCount` = 0 (fresh container). |
| 2026-04-27T16:48:00Z  | 131,788 kB          | 131,788 kB| 125     | 640 MiB        | 772 MiB        | 3               | T+12h cron snapshot (NEW pod, ~3h 7m old). cgroup.peak DROPPED to 772 MiB — that's the new container's high-watermark (peak only counts since the new cgroup was created); it is *not* a regression of the cumulative peak across pods. cgroup.current is 640 MiB, driven by the resumed claude session (active_children=3). top-by-RSS: claude=275 MiB, vibe-kanban=128 MiB, npm=123/106/93 MiB (three concurrent), node=87/67 MiB. vibe-kanban itself ~128 MiB — close to T+0's 128 MiB → Rust server's resident set is stable across the rollout. *(Cron-captured sample; commit was backfilled because the script's `git checkout` against `/home/claude/repos/agent-images` failed; vk-snap.sh now uses the dedicated PVC clone.)* |
| 2026-04-27T16:53:10Z  | 132,260 kB          | 132,260 kB | 125     | 526 MiB        | 772 MiB        | 3               | T+12h auto-snapshot. PID 7, top by RSS: claude:302864/2067,vibe-kanban:132260/7,npm:95452/2090,node:88488/2142,kubectl:56788/2906,ps:4332/2949,bash:3088/2896,vk-snap.sh:3008/2903. |
| 2026-04-27T20:48:00Z  | 221,168 kB          | 221,168 kB | 108     | 1.13 GiB       | 1.45 GiB       | 0               | T+16h auto-snapshot. PID 7, top by RSS: vibe-kanban:221168/7,ps:4268/11317,bash:3100/11298,awk:1848/11319,bash:1656/11316,head:1452/11318,tini:1276/1. |
| 2026-04-28T00:48:00Z  | 230,008 kB          | 230,008 kB | 115     | 1.14 GiB       | 1.45 GiB       | 0               | T+20h auto-snapshot. PID 7, top by RSS: vibe-kanban:230008/7,ps:4272/11575,bash:3076/11556,awk:1912/11577,bash:1560/11574,head:1292/11576,tini:1276/1. |
| 2026-04-28T04:48:00Z  | 105,332 kB          | 105,332 kB | 100     | 187 MiB        | 2.00 GiB       | 0               | T+24h auto-snapshot. PID 7, top by RSS: vibe-kanban:105332/7,ps:4280/1306,bash:3048/1287,awk:1816/1308,bash:1524/1305,head:1340/1307,tini:1300/1. |
<!-- snapshots-retake-end -->

### OOMKills observed (retake window)

Two classes of kill observed across the retake window's two pod spans:

**Span 1 — pod `secure-agent-pod-b6b9bcd5d-jmc7n` (T+0 → T+9h, baseline restartCount=1):**
No in-window OOMKills. The pod was terminated by a Deployment rollout at T+9h (2026-04-27T13:40:36Z); cgroup.peak at last sample (T+5h, 2026-04-27T09:27Z) was 1.82 GiB — well below the 2 GiB cap. The prior OOMKill that created this container (at 2026-04-27T04:48:33Z, captured in the anchor) is considered the event that opened the retake window.

**Span 2 — pod `secure-agent-pod-69677554b6-2xg7j` (T+9h → end, baseline restartCount=0):**
20 OOMKills in 17.4h (2026-04-27T13:40Z → 2026-04-28T07:03Z) — rate ≈ **1 kill per 52 minutes**. Kubelet exposes only the most-recent Last State:

| field                    | value                               |
|--------------------------|-------------------------------------|
| Last State reason        | OOMKilled                           |
| Last State exit code     | 137                                 |
| Last State container started | 2026-04-28T05:57:50Z           |
| Last State container finished| 2026-04-28T06:00:48Z (2m 58s lifetime) |
| Current container started | 2026-04-28T06:00:59Z              |
| restartCount at analysis | 20 (as of 2026-04-28T07:03Z)       |

Earlier kill timestamps are beyond the 1h kubelet-event retention and are not recoverable. The T+24h snapshot (`cgroup.peak = 2,148,085,760 B = 1.000280 × 2 GiB`) provides the pre-kill watermark for the kill that occurred between T+20h and T+24h.

**Escalation note:** the pre-retake rate was 6 kills in 48h (1/8h). Span 2 shows 1/52min — 9× more frequent. The image on Span 2 is `dc414b4` (PR #13 merge). That PR is docs-only; however, the image build pipeline pulls the latest vibe-kanban fork binary. If the upstream `vibe-kanban` binary changed between the Phase 1 image (`ed62d429`) and `dc414b4`, that would explain the escalation. Phase 3 should cross-check the binary SHA on the current pod against Phase 1's `d3bbcd70b1…`.

### Audit activity per hour (retake window)

**Instrumentation gap:** VK-spawned agent sessions run as children of `vibe-kanban` inside the `vk-local` container's PID and cgroup namespace. Their tool-use events are not captured in kali's `~/.willikins-agent/audit.jsonl` (which only records commands run from kali's shell). The retake window contains 0 audit entries. The Pearson r vs audit_lines is therefore undefined.

Agent sessions observed indirectly via `active_children` in the snapshot table: T+0 (active=3), T+12h (active=3); all other samples show active=0.

### Correlation (retake window)

| hour | max_cgroup_cur_mib | active_children (sample) | oomkill_in_hour |
|------|-------------------:|:------------------------:|:---------------:|
| T+0  |                733 | 3                        | 0               |
| T+1  |                473 | 0                        | 0               |
| T+2–T+4 | ~476 (interp.) | 0                       | 0               |
| T+5  |                479 | 0                        | 0               |
| T+6–T+8 | ~479 (interp.) | 0                       | 0               |
| T+9  | — (disruption)     | —                        | 0 (rollout, not OOM) |
| T+10–T+11 | — (new pod startup) | —                  | 0               |
| T+12 |                640 | 3                        | 0               |
| T+13–T+15 | ~808 (interp.) | unknown                 | unknown         |
| T+16 |              1,130 | 0                        | unknown         |
| T+17–T+19 | ~1,133 (interp.) | unknown               | unknown         |
| T+20 |              1,140 | 0                        | 0 (no peak spike yet) |
| T+21–T+23 | — (OOMKills; cgroup resets) | —            | **yes** (≥1)  |
| T+24 |                187 | 0                        | **yes** (peak=2.00 GiB on prior container) |

**Pearson r (active_children vs cgroup_cur_mib, n=7 sampled points):** r = 0.007 (≈ 0). This does NOT mean memory is uncorrelated with workload — it means the **lag** is too long for a point-in-time snapshot to capture. Active sessions exit but leave ~900 MiB of file cache in the cgroup that the kernel does not reclaim until pressure. By the time the next sample fires (4h later), active_children=0 but cgroup.current is still high, inverting the expected correlation.

**Idle drift (T+1h → T+5h, same pod, no children):** +1.5 MiB/h — below the 10 MiB/h leak threshold.

**Rubric classification:**
- r ≤ 0.5 ✓
- idle drift < 10 MiB/h ✓
- → **bounded, favors A or B** (not a leak → not C)

### Additional contributing factors (from parallel investigation thread)

Two findings from a concurrent thread are relevant and incorporated here before Phase 3 makes the formal call:

**1. npm cache balloon — 12 GiB at `/home/claude/.npm`**

The npm `_cacache` and `_npx` directories on the PVC have grown to 12 GiB with no automatic pruning. When claude sessions load MCP servers (e.g., `@upstash/context7-mcp`, others) via `npm exec`, the kernel reads package files from this cache into the cgroup's page cache. After the session exits, these file-backed pages remain in the cgroup's `memory.current` (reclaimable under pressure, but not freed eagerly). This directly explains the T+16h/T+20h idle cgroup.current of ~1.13–1.14 GiB (vibe-kanban ~220 MiB + ~900 MiB retained file cache from packages loaded in the T+12h session). The 12 GiB disk footprint is also a PVC reliability risk independent of cgroup pressure.

**2. VK worktrees not cleaned up — ~15–20 MiB each retained by vibe-kanban**

vibe-kanban's own RSS grew from 128 MiB (T+0, container fresh, 0 active worktrees) to 198 MiB (07:00Z observation, 4 active worktrees: `15d8-ffe-67-gh-8`, `609e-ffe-75-gh-60`, `7bbf-ffe-69-gh-58`, `9cbc-ffe-72-gh-59`). The per-worktree memory load is approximately (198−128)/4 ≈ **17 MiB of vibe-kanban heap per live worktree**. At T+16h/T+20h (vibe-kanban 221–230 MiB, active=0), several worktrees from earlier sessions had not been pruned, accounting for 93–102 MiB above the post-restart baseline. This is not a random-walk leak — it is bounded by the number of live worktrees — but worktree accumulation with no cleanup policy is a steady-state memory growth vector. A `git worktree prune` on the repo after each task completes would reclaim this.

**Revised cgroup fill sequence (typical kill event):**

1. vibe-kanban idle baseline: ~128 MiB (fresh container, 0 worktrees) → grows to ~200–230 MiB as worktrees accumulate
2. Session starts: claude (~300 MiB) + npm (~90 MiB) + node (~90 MiB) = +480 MiB → cgroup ~680–710 MiB
3. Session ends: child RSS freed, but ~900 MiB of npm package file-cache retained → cgroup ~1.1 GiB
4. Second session starts: another +480 MiB → cgroup ~1.6 GiB
5. Third session starts (or second session peaks): cgroup reaches 2 GiB → OOMKill

---

## Phase 3 — Decision (pending)

> **Note on option definitions:** Option B below is a refinement of the original plan's "upstream cap: working-set is unbounded under workload X" to reflect the Phase 1 discovery that `vibe-kanban` itself is only ~147 MiB RSS — an "upstream cap in the Rust binary" no longer matches the observed behavior. The cgroup fills with *child processes*, so the Phase 3 agent chooses between raising the limit, capping/relocating the child workload, or finding a leak. If the Phase 3 agent prefers the original framing, keep it — but the numbers from Phase 1 have to be reconciled either way.

One of:
- **A (raise limit):** recommended limit = _N_ Gi, justification = peak + margin. Follow-up deploy plan against `derio-net/frank`.
- **B (cap concurrency / re-parent children):** the cgroup fills because `vibe-kanban` spawns `claude`/`npm`/`node` as children of the vk-local cgroup. Options: run them in the `kali` sibling container, enforce a max concurrent-sessions config, or move to a per-task pod. File upstream issue/PR against the vibe-kanban fork.
- **C (leak):** a single `vibe-kanban` or `claude` process grows monotonically at idle by _rate/h_. File code-level fix against the offending repo.

## Phase 3 — Analysis & recommendation

### Pattern classification (P3.T1.S1)

**Pattern: Sawtooth, reset at OOMKill (workload-driven burst), with three compounding fill sources.**

The Phase 2 retake provides a complete picture. The cgroup does not fill from a single cause:

**Source 1 — Active session child RSS (~480 MiB per session):**
Per the Phase 1 process tree and retake T+0 sample: claude ~300 MiB + npm ~90 MiB + node ~90 MiB = ~480 MiB of child RSS per active session. These are released when the session exits.

**Source 2 — Retained npm file-cache (~900 MiB, post-session):**
After a session exits and child processes are reaped, the npm `_cacache`/`_npx` package files remain in the cgroup's page cache (file-backed, reclaimable under pressure, but not eagerly freed). At T+16h and T+20h (0 active sessions), cgroup.current was ~1.13 GiB — vibe-kanban accounts for ~220 MiB, leaving ~910 MiB of retained file cache. The npm cache on PVC has grown to 12 GiB without pruning, ensuring a large hot set.

**Source 3 — vibe-kanban heap per live worktree (~17 MiB each):**
vibe-kanban RSS grew from ~128 MiB (fresh start, 0 worktrees) to ~198 MiB with 4 active worktrees — approximately 17 MiB per worktree retained in heap. At T+16h/T+20h, vibe-kanban was 221–230 MiB with no active sessions, consistent with several un-pruned worktrees adding ~93–102 MiB above the fresh baseline. This is bounded (not a random walk), but accumulates without a cleanup policy.

**Typical OOMKill sequence:**
1. Container starts fresh: vibe-kanban ~128 MiB, cgroup ~128 MiB
2. Worktrees accumulate: vibe-kanban grows to ~200–230 MiB
3. Session runs: +480 MiB → cgroup ~680–710 MiB
4. Session exits: child RSS freed, ~900 MiB npm file-cache retained → cgroup ~1.1 GiB
5. Second session starts: +480 MiB → cgroup ~1.6 GiB
6. Third session starts (or second peaks): → cgroup hits 2 GiB → **OOMKill**

**OOMKill rate escalation:**
- Historical (pre-retake): ~1 kill per 8 hours
- Retake Span 2 (`dc414b4` image): 20 kills in 17.4h = **1 kill per 52 minutes** (9× faster)

The escalation is unexplained by data alone. Two hypotheses: (a) the new image (`dc414b4`, built from PR #13 merge) pulled a newer vibe-kanban binary that uses more memory or spawns sessions differently; (b) the kali tmux/mosh additions (commit `eb6ae08`) enabled more persistent agent connections, increasing concurrent session count. **Phase 3 action item:** verify the binary SHA on pod `secure-agent-pod-69677554b6-2xg7j` against Phase 1's `d3bbcd70b1…` — if identical, the escalation is workload-driven; if different, the binary itself may have regressed.

**Option C (leak) — RULED OUT:**
Idle drift at T+1h→T+5h (same pod, 0 active children): +1.5 MiB/h — below the 10 MiB/h leak threshold. vibe-kanban's worktree heap growth is bounded by worktree count, not time. Pearson r (active_children vs cgroup_cur_mib) = 0.007 ≈ 0, which reflects lag (file-cache persists after exit) rather than independence. No evidence of unbounded monotonic growth in any process.

### Session budget (P3.T1.S2)

Using the retake's observed saturated-idle baseline (~1,157 MiB at T+16h/T+20h with 0 active sessions) and the per-session active child cost (~480 MiB):

| Concurrent sessions | Estimated cgroup.current | Limit needed (×1.25, ↑256 MiB) | Notes |
|---:|---:|---:|---|
| 0 (idle, fresh) | ~128 MiB | — | fresh container, 0 worktrees |
| 0 (idle, saturated) | ~1,157 MiB | — | accumulated file-cache + worktree heap |
| 1 | ~1,637 MiB | 2,048 MiB (2 Gi) | tight |
| 2 | ~2,117 MiB | 2,560 MiB (2.5 Gi) | **current 2 Gi kills here** |
| 3 | ~2,597 MiB | 3,328 MiB (3.25 Gi) | |
| 4 | ~3,077 MiB | 3,840 MiB (3.75 Gi → 4 Gi) | preliminary Phase 2 call |
| 5 | ~3,557 MiB | 4,352 MiB (4.25 Gi) | |
| 6 | ~4,037 MiB | 5,120 MiB (5 Gi) | |
| 7 | ~4,517 MiB | 5,632 MiB (5.5 Gi) | |
| **8 (current UI max)** | **~4,997 MiB** | **6,144 MiB → 6,400 MiB (6.25 Gi)** | formula minimum |

> **Note on npm file-cache scaling:** The ~900 MiB file-cache is assumed roughly fixed regardless of session count (the kernel deduplicates file-backed pages from the same PVC files across sessions loading the same MCP packages). If sessions load distinct packages, this could scale upward; the model is conservatively fixed at one saturated-idle's worth.

**Recommended limit for 8 concurrent sessions: 8 Gi (8,192 MiB).**
Formula minimum is 6,400 MiB (6.25 Gi). 8 Gi provides ~1.6 Gi of margin above the formula minimum — warranted here because:
- The formula uses saturated-idle baseline, which itself may grow as the npm cache expands
- The 9× kill-rate escalation in Span 2 suggests the true peak load may exceed the model
- 8 Gi is a clean K8s limit value (round power-of-two Gi)

If the housekeeping actions (npm cache prune + worktree TTL) are deployed simultaneously, the saturated-idle baseline drops from ~1,157 MiB to closer to ~200 MiB, and the per-session model gives 8 sessions at 200 + 8×480 = 4,040 MiB → ×1.25 = 5,050 MiB → **5 Gi**, reducing the required limit substantially. The 8 Gi recommendation holds as a safe initial value; a re-review is appropriate after housekeeping is in place.

### Option analysis

#### Option C — Leak fix: RULED OUT

Idle drift 1.5 MiB/h; worktree heap growth is bounded by worktree count; cgroup resets cleanly after OOMKill. No unbounded monotonic growth observed. **No code-level fix needed.**

#### Option B — Architectural: VALID, NOT IMMEDIATE

Three sub-options, in order of ascending implementation complexity:

**B-housekeeping (lowest cost, highest ROI — do concurrently with A):**
- `npm cache clean --force` or `npm cache verify` in a periodic kali cron (or triggered before session start) — eliminates the ~900 MiB file-cache contributor entirely, dropping saturated-idle from ~1,157 MiB to ~220 MiB. Single shell command; no vibe-kanban changes needed.
- `git worktree prune` in vibe-kanban's post-task cleanup path, or a worktree TTL policy — eliminates the ~17 MiB/worktree heap accumulation in vibe-kanban's RSS. Small upstream change.
- Together these would reduce the required limit for 8 concurrent sessions from 8 Gi to ~5 Gi.

**B1 — Max-concurrent-sessions config (short-term, upstream vibe-kanban change):**
- Add a configurable cap (e.g., `max_concurrent_executions: 4`) to the vibe-kanban config schema (already at `config_version: v8`). Excess sessions queue rather than spawn.
- With cap=4 and housekeeping in place: 220 + 4×480 = 2,140 MiB → ×1.25 → 2,675 MiB → **3 Gi** sufficient.
- Recommended as follow-up after housekeeping; allows the A-limit to be dialled back once B-housekeeping + B1 are deployed.

**B2 — Delegate execution to kali sibling cgroup (long-term):**
- Spawn claude/node/npm child processes in the kali cgroup (32 Gi limit). vk-local cgroup shrinks to vibe-kanban only (~200 MiB steady-state). Requires upstream IPC/relay changes to vibe-kanban. Worth tracking; not immediately actionable.

**B3 — Per-task Kubernetes Jobs (future):**
- Each execution gets its own pod with dedicated cgroup. Full isolation; highest complexity. Appropriate at 10+ concurrent sessions or if per-session security isolation becomes a requirement.

#### Option A — Raise cgroup limit: RECOMMENDED (immediate)

**Recommended limit: 8 Gi (8,192 MiB)** — covers the stated 8-session maximum at saturated-idle baseline with margin. Deploy-plan target: `apps/secure-agent-pod/manifests/deployment.yaml:143` in `derio-net/frank`.

If housekeeping (npm cache prune + worktree TTL) ships concurrently, the effective headroom increases substantially; the 8 Gi limit can be reassessed and potentially lowered to 4–5 Gi at that point.

### Decision

**Chosen: A (immediate) + B-housekeeping (concurrent) + B1 (follow-up).**

| Track | Action | Urgency | Target repo |
|---|---|---|---|
| **A** | Raise `vk-local` limit `2Gi` → `8Gi` | **Now** (20 kills/17.4h crash-loop) | `derio-net/frank` |
| **B-housekeeping** | npm cache prune cron + worktree TTL | Concurrent with A | `derio-net/frank` (cron), vibe-kanban fork (worktree TTL) |
| **B1** | `max_concurrent_executions` config cap | After B-housekeeping | vibe-kanban fork + frank config |
| **B2** | Delegate execution to kali cgroup | Long-term | vibe-kanban fork |
| **Action item** | Verify binary SHA on `dc414b4` pod vs Phase 1 | Before filing B2 | observation only |

**Rationale:** C is excluded. The crash-loop (1 kill/52min) requires an immediate limit bump to restore stability — that is A. B-housekeeping removes the two biggest non-session contributors (~900 MiB file-cache, ~17 MiB/worktree heap) at minimal cost and substantially reduces the required limit. B1 enforces the workload bound in software once housekeeping is in place, enabling future limit reduction. B2/B3 are parked until B1 data shows whether they are needed.

**Implementation:** See `derio-net/frank#140` (brainstorming issue filed for the implementation plan).

---

## Appendix — commands and raw data

Captured 2026-04-23 20:37–20:45 UTC from the `frank` kube context (`kubectl config current-context == frank`).

### A.1 Binary metadata

```bash
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  bash -c 'ls -lh /usr/local/bin/vibe-kanban; stat /usr/local/bin/vibe-kanban;
           sha256sum /usr/local/bin/vibe-kanban; head -c 4 /usr/local/bin/vibe-kanban | od -c | head -1'
```

Output:
```
-rwxr-xr-x 1 claude claude 134M Apr 18 06:40 /usr/local/bin/vibe-kanban
Size: 139643680   Modify: 2026-04-18 06:40:55 +0000
d3bbcd70b187e757f41426db6915886e8e967640ab958efa3b88b5147679b9bf  /usr/local/bin/vibe-kanban
0000000 177   E   L   F        # ELF magic confirmed; `file` / `readelf` not installed in the image
```

### A.2 ldd (allocator determination)

```bash
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  ldd /usr/local/bin/vibe-kanban
```

Output (no `libjemalloc*` → glibc malloc):
```
linux-vdso.so.1
libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6
libgcc_s.so.1 => /lib/x86_64-linux-gnu/libgcc_s.so.1
libm.so.6 => /lib/x86_64-linux-gnu/libm.so.6
/lib64/ld-linux-x86-64.so.2
```

### A.3 HTTP surface enumeration

```bash
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- bash -c '
  for p in /api/health /api/info /api/version /api/projects /api/tasks \
           /api/executions /api/config /api/metrics /api/events /metrics; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:8081${p})
    ct=$(curl -sI --max-time 3 http://localhost:8081${p} 2>/dev/null \
         | grep -i "^content-type" | head -1 | tr -d "\r\n")
    echo "${p} | ${code} | ${ct}"
  done'
```

Output (only `application/json` and `text/event-stream` entries are real routes; the rest fall through to the SPA `index.html`):
```
/api/health     | 200 | content-type: application/json
/api/info       | 200 | content-type: application/json
/api/version    | 200 | content-type: text/html             ← SPA fallback
/api/projects   | 200 | content-type: text/html             ← SPA fallback
/api/tasks      | 200 | content-type: text/html             ← SPA fallback
/api/executions | 200 | content-type: text/html             ← SPA fallback
/api/config     | 405 |                                     ← real route, method not allowed
/api/metrics    | 200 | content-type: text/html             ← SPA fallback (no Prom endpoint)
/api/events     | 200 | content-type: text/event-stream     ← SSE, real
/metrics        | 200 | content-type: text/html             ← SPA fallback (no Prom endpoint)
```

`/api/info` body (excerpt):
```json
{"success":true,"data":{"version":"0.1.42","config":{"config_version":"v8", ...}}}
```

### A.4 Process tree snapshot (sampled 2026-04-23 20:40 UTC; single sample)

```bash
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  ps -eo pid,ppid,rss,vsz,comm --sort=pid
```

Output (RSS in KiB):
```
  PID  PPID    RSS     VSZ COMMAND
    1     0   1300    2488 tini
    7     1 150188 8948900 vibe-kanban
 1513     7 389632 74789388 claude
 1535  1513  81664 1331408 npm exec @upsta
 1586  1535   1712    2592 sh
 1587  1586  85912 22080084 node
24145  1513   3028    4072 bash
24245 24145  53536 1288896 kubectl
```

Sum of per-process RSS ≈ 760 MiB, matching cgroup `memory.current` (below) to within a few MiB — so the cgroup fill is fully accounted for by this tree. Caveat: a single sample; Phase 2 will produce the time series.

### A.5 vibe-kanban-only memory detail (PID 7 at same sample)

```bash
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  bash -c 'grep -E "^(VmPeak|VmSize|VmHWM|VmRSS|RssAnon|RssFile|VmData|Threads)" /proc/7/status;
           echo "---"; cat /proc/7/smaps_rollup | grep -E "^(Rss|Pss|Anonymous|Private_Dirty)"'
```

Output excerpt: `VmRSS ≈ 150,188 kB`; `Pss 148,221 kB`; `Pss_Anon 106,472 kB` (≈71 % private-dirty anon heap). Rust server process memory is modest — the cgroup stress comes from children.

### A.6 cgroup snapshot (same sample, cgroup v2)

```bash
kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c vk-local -- \
  bash -c 'cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.max; \
           echo "---"; head -15 /sys/fs/cgroup/memory.stat'
```

Output:
```
memory.current = 791,285,760  B  (755 MiB)
memory.peak    = 1,367,040,000 B (1304 MiB)        # since container start (~14h window)
memory.max     = 2,147,483,648 B (2 Gi)            # cgroup limit
anon    429,047,808
file    308,011,008
kernel   45,711,360
kernel_stack 3,178,496
sock      4,804,608
```

### A.7 VictoriaMetrics availability (the big tooling finding)

Base endpoint used for all VM queries (reachable from any pod in the cluster):
```
http://vmsingle-victoria-metrics-victoria-metrics-k8s-stack.monitoring.svc:8428/api/v1
```

Confirming that cadvisor scrape covers *only* `raspi-1` / `raspi-2`, not `gpu-1`:

```bash
kubectl run -n monitoring vk-probe --rm -i --restart=Never --image=curlimages/curl:latest --command -- \
  curl -sG "http://vmsingle-victoria-metrics-victoria-metrics-k8s-stack.monitoring.svc:8428/api/v1/query" \
       --data-urlencode 'query=count by (node) (container_memory_working_set_bytes)'
```

Output (abridged):
```json
{"status":"success","data":{"resultType":"vector","result":[
  {"metric":{"node":"raspi-1"},"value":[...,"47"]},
  {"metric":{"node":"raspi-2"},"value":[...,"43"]}
]}}
```

No `node=gpu-1` entry → no cadvisor series for the node where `secure-agent-pod` runs. This is the claim that drives the entire Phase 2 redirect; re-running the query above is the verification path.

Confirming that `container_memory_working_set_bytes{container="vk-local"}` is empty:

```bash
# same probe-pod pattern — query = container_memory_working_set_bytes{container="vk-local"}
# result: {"data":{"resultType":"vector","result":[]}}
```

Confirming that `kubectl top` has no backend:

```
$ kubectl top pod -n secure-agent-pod --containers
error: Metrics API not available
```

Confirming that kube-state-metrics *does* track this container (so OOM correlation still works):

```bash
# query = kube_pod_container_status_last_terminated_reason{namespace="secure-agent-pod",container="vk-local",reason="OOMKilled"}
# result: 1 series, value=1  (most-recent termination was an OOMKill)

# query = kube_pod_container_status_restarts_total{namespace="secure-agent-pod",container="vk-local"}
# result: 8

# query = increase(kube_pod_container_status_restarts_total{...vk-local}[24h])
# result: 2
```

