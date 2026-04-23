# vk-local Memory Profile — Findings

## Context

Deviation D4 of `docs/superpowers/plans/2026-04-18-persistent-agent-reliability-design.md` flagged 6 OOMKills in ~48h at the 2Gi limit. This doc is the cross-phase scratchpad for the follow-up plan `docs/superpowers/plans/2026-04-22-vk-local-memory-profile.md`.

**Status:** Phase 1 complete (Workload survey & tooling check). Phase 2 (Observation window) and Phase 3 (Analysis & recommendation) pending.

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
- **Stripped:** not confirmed (no `readelf`); size ≈ 133 MiB suggests debug symbols retained or panic-backtrace infra is present.
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

1. **Primary sampler:** a 60-second poll of `/proc/7/status` (VmRSS, VmHWM, Threads) + `/sys/fs/cgroup/memory.current` + `memory.peak` via `kubectl exec -c vk-local`, driven from a long-running loop on an external host (Frank control host or another cluster workload). Record per-process RSS for `vibe-kanban` and each spawned child separately — the process tree is the signal, not the single PID.
2. **OOM correlation:** poll `kube_pod_container_status_last_terminated_timestamp` + `_reason` from VictoriaMetrics every minute — this *is* scraped for this container.
3. **Out-of-scope escalation:** fixing the cadvisor scrape coverage for `gpu-1` is a separate deploy-plan item against `derio-net/frank`; do not do it from this plan, but note it in the final decision.

---

## Phase 2 — Observation window (pending)

### Observation window

- Start: _(UTC ISO)_
- End: _(UTC ISO)_
- OOMKills observed: _(N)_
- Pre-kill memory.peak: _(MB)_
- Idle cgroup.current baseline (no active claude session): _(MB)_
- Steady-state cgroup.current (1 active claude): ~755 MiB (single-sample, from Phase 1)

### Manual RSS snapshots (T+0, T+4h, T+8h, T+12h, T+16h, T+20h, T+24h)

| ts_utc | VmRSS (vibe-kanban) | VmHWM | Threads | cgroup.current | cgroup.peak | active_children |
|--------|--------------------:|------:|--------:|---------------:|------------:|----------------:|
|        |                     |       |         |                |             |                 |

### Activity correlation

- Audit log lines per hour (kali `~/.willikins-agent/audit-archive/audit-YYYYMMDD.jsonl`):
- Claude session spawn count per hour (derived from `ps` sampler):
- Correlation (r) between hourly peak cgroup.current and audit lines/hour:

---

## Phase 3 — Decision (pending)

One of:
- **A (raise limit):** recommended limit = _N_ Gi, justification = peak + margin. Follow-up deploy plan against `derio-net/frank`.
- **B (cap concurrency / re-parent children):** the cgroup fills because `vibe-kanban` spawns `claude`/`npm`/`node` as children of the vk-local cgroup. Options: run them in the `kali` sibling container, enforce a max concurrent-sessions config, or move to a per-task pod. File upstream issue/PR against the vibe-kanban fork.
- **C (leak):** a single `vibe-kanban` or `claude` process grows monotonically at idle by _rate/h_. File code-level fix against the offending repo.

**Chosen:** _(A | B | C)_. **Rationale:** _(para)_.

---

## Appendix — commands and raw data

Captured 2026-04-23 20:37–20:45 UTC from the `frank` kube context.

```text
# Binary
/usr/local/bin/vibe-kanban: 139643680 B, mtime=2026-04-18T06:40:55Z
sha256: d3bbcd70b187e757f41426db6915886e8e967640ab958efa3b88b5147679b9bf

# ldd
linux-vdso.so.1
libc.so.6
libgcc_s.so.1
libm.so.6
ld-linux-x86-64.so.2

# /api/info
{"success":true,"data":{"version":"0.1.42","config":{"config_version":"v8", ...}}}

# cgroup snapshot
memory.current = 791,285,760 B  (755 MiB)
memory.peak    = 1,367,040,000 B (1304 MiB)
memory.max     = 2,147,483,648 B (2 Gi)

# memory.stat (excerpt)
anon  429,047,808
file  308,011,008
kernel 45,711,360
kernel_stack 3,178,496
sock   4,804,608

# process tree RSS (sum 760 MiB with 1 active claude)
tini         1300
vibe-kanban  150188
claude       389632
npm           81664
node          85912
kubectl       54492
```

VictoriaMetrics query base used: `http://vmsingle-victoria-metrics-victoria-metrics-k8s-stack.monitoring.svc:8428/api/v1`.

