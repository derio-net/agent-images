# Persistent Agent Reliability — Design

*Date: 2026-04-18*
*Status: In Progress*

## Context

The Willikins persistent agent runs on the `secure-agent-pod` as a per-repo `claude remote-control` session, watchdogged every 5 minutes by `scripts/session-manager.sh`. A 2026-04-18 triage of the pod surfaced six findings:

| # | Finding | Severity |
|---|---|---|
| 1 | Phantom sessions accumulate in claude.ai — 39 environments, 43 sessions since 2026-03-31. Watchdog has restarted 40 times; each restart allocates a new server-side `env_…`/`session_…` that no graceful disconnect ever closes. | High (user-visible noise, +2/day steady state) |
| 2 | `Server unreachable for 11 minutes, giving up.` disconnect loops — ~1/day average, bursts of 7 on bad days. Session dies, watchdog relaunches → new phantom (see #1). Root cause unknown (network? Anthropic side?). | Medium |
| 3 | `/home/claude/.willikins-agent/audit.jsonl` does not exist. PostToolUse hook in `guardrails-hook.py` is silently not writing. Daily audit digest has reported "no log found" for 10+ days. | Medium (security-observability regression) |
| 4 | `session-willikins.log` is 332 MB of ANSI escape sequences. No rotation. | Low (disk creep) |
| 5 | `vk-issue-bridge.py` logs a `derio-net/derio-profile` not-found warning on every 2-min poll. Benign, but noise that masks real warnings. | Low |
| 6 | Only one session is configured (`WILLIKINS_REPOS=/home/claude/repos/willikins:willikins`). Design intent per `WILLIKINS_REPOS` naming is multi-session. Deliberate for now — not addressed here. | N/A |

## Decision

Ship a bundle of targeted fixes in three agentic phases + one manual soak. Scope is deliberately narrow — investigation of the disconnect-loop root cause (#2) is deferred to the soak phase and promoted to a follow-up plan only if soak data implicates a fixable local cause.

### Approach

**Phase 0 — Spike:** determine whether `claude` CLI exposes a close/disconnect for remote-control environments. Output: findings doc. Gates Phase 1.

**Phase 1 — Graceful shutdown:** SIGTERM trap in `session-manager.sh`, signal propagation to the `claude remote-control` child, and a disconnect action whose shape is chosen by Phase 0. If the fix requires a K8s preStop hook, the deployment change is filed as a separate Issue in `derio-net/frank` (one-plan-one-repo).

**Phase 2 — Housekeeping batch:** audit hook write-path bug, log rotation config, vk-bridge warning patch. Independent from Phase 1, ships in parallel.

**Phase 3 — 24h soak:** deploy, observe, record. If disconnect loops continue past the soak, a follow-up plan opens against the Frank network layer.

### Non-goals

- Root-causing the 11-min-unreachable loops (deferred to soak observation).
- Multi-session configuration (`WILLIKINS_REPOS` with multiple repos) — separate initiative.
- Retiring the audit pipeline — we fix it, not remove it, per the 2026-03-30 security design.
- Any change to the Claude CLI itself. If Phase 0 finds no close API, we document the limitation and move on.

## Threat model deltas

None. No new capabilities, no loosened guardrails. The audit-hook fix restores a layer the 2026-03-30 design already specified.

## Risks

| Risk | Mitigation |
|---|---|
| Phase 0 finds no close API; phantoms continue to accumulate at a slower rate. | Document the limitation; file upstream issue / feature request with Anthropic. Graceful shutdown still helps for the common case (pod redeploy). |
| SIGTERM trap breaks existing restart behavior. | TDD — test the trap in isolation before wiring it into the script. |
| Log rotation truncates mid-write and corrupts an active session log. | Use `copytruncate` semantics (or size-capped tail) rather than rename+HUP. |
| vk-bridge patch masks legitimate repo-discovery failures. | Patch the specific `derio-profile` case or make the warning levelled, not suppressed globally. |

## Implementation Plans

| Plan | Repo | File | Status | Depends on |
|------|------|------|--------|------------|
| Persistent Agent Reliability | derio-net/agent-images | `docs/superpowers/plans/2026-04-18-persistent-agent-reliability.md` | Not Started | — |
| Persistent Agent Reliability Implementation Plan |  | `docs/superpowers/plans/2026-04-18-persistent-agent-reliability.md` | In Progress | — |
| vk-bridge Warn-Pattern Broadening Implementation Plan |  | `docs/superpowers/plans/2026-04-22-vk-bridge-warn-patterns.md` | Not Started | — |
| vk-local Memory Profiling Implementation Plan |  | `docs/superpowers/plans/2026-04-22-vk-local-memory-profile.md` | Not Started | — |
| Silent-Reconnect Phantom Reaper Implementation Plan | derio-net/agent-images | `docs/superpowers/plans/2026-04-22-silent-reconnect-phantoms.md` | Not Started | — |
