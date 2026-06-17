# agent-session persistence + liveness (agent-images)

Fixes surfaced by the alert-agent live Test Plan. Three driver/base changes, gating the frank plan.

- **C (Phase 1) — liveness check:** `ensure_session` must stop trusting bare `has-session`. A session
  can exist as a DEAD bash shell (tmux-continuum restored it, or claude crashed). Probe the pane for
  the `❯` REPL prompt within a short bounded wait; if it isn't a live claude REPL, kill + recreate.
  This is the load-bearing fix — it makes the driver self-correcting regardless of how a dead session
  appeared (it's what actually broke the operator's DMs).
- **E (Phase 2) — persistence + context mgmt:** launch `claude --session-id <uuidv5(session_id)>
  --permission-mode auto` so each named session resumes a PVC-persisted conversation across restarts
  (memory). On a request after >12h idle, `/clear` first (fresh conversation, same stable id). When
  context >60%, `/compact` (best-effort; the parse target + the --session-id resume behaviour are
  live-verified on the pod — A–D don't depend on E, so it can degrade to fresh-per-launch).
- **B (Phase 3) — continuum conditional:** `agent-shell-base` tmux config disables continuum-restore
  when `AGENT_TMUX_RESTORE=off`, default-on so human shells are unchanged. Cleanliness on top of C.

Gates the frank plan: merge → CI builds a new multi-agent-shell tag → frank sets the env on
alert-agent + n8n-01 and bumps both image SHAs. Tests via the PATH-injected FAKE_TMUX stub; RED
verified against HEAD.
