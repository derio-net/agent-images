# agent-session extraction → multi-agent-shell image (agent-images — Plan A)

**Status:** Planned
**Spec:** `derio-net/frank:docs/superpowers/specs/2026-06-15--obs--agentic-alert-helper-design.md` (Part A)
**Repo:** derio-net/agent-images

## Why

The persistent-agent driver (`agent-session`) is currently a ConfigMap copy-pasted inside frank's
`apps/n8n-01/`. A second consumer (the alert-agent) and a third are coming. This bakes it **into the
multi-agent-shell image** (beside `notify-telegram.sh`) as a versioned, reusable contract every
consumer shares — and is the **gating deliverable**: frank's two plans consume the resulting image tag.

## What it produces

A new `multi-agent-shell` image tag carrying:
- `/usr/local/lib/multi-agent-shell/agent-session` (+ `/usr/local/bin` symlink) — the driver,
  stdlib-only, genericized `STOA_*`→`AGENT_SESSION_*` (with deprecated aliases).
- A **configurable per-agent launch profile** (claude default; antigravity/codex selectable) — the
  `agent` field is already in the API; `ensure_session` is generalized off its hardcoded claude.
- A baked **s6 longrun** (`/etc/services.d/agent-session-server/run`, sshd precedent) that serves the
  `agent-session` HTTP endpoint when `AGENT_SESSION_SERVE=1` (default off; consumers opt in) — no
  postStart hook needed by consumers.
- The contract documented in the image README; pytest tests (modeled on the existing `kali/tests/`
  pytest, since `multi-agent-shell/tests/` is bats-only) + per-agent-dispatch + alias coverage.

## Phase map

1. **Bake + genericize (TDD)** — pytest port reading the baked path RED; move driver into rootfs +
   `AGENT_SESSION_*` aliases + Dockerfile symlink GREEN.
2. **Per-agent launch profile (TDD)** — dispatch tests RED; generalize `ensure_session` GREEN.
3. **s6 longrun** — `AGENT_SESSION_SERVE`-gated service mirroring sshd; bats smoke.
4. **README + branch image** — document the contract; `gh workflow run build.yaml --ref` and
   **confirm a branch-tagged image publishes** (the tag frank consumes).

## Notes

- Cross-repo spec ref (`derio-net/frank:…`) — `fr plan self-review` may warn it doesn't resolve in
  this repo; that's expected for a cross-repo spec, not an error.
- agent-images CI builds on `push:main` (paths-ignore `docs/**`); a branch is validated via the
  manual `workflow_dispatch` (`--ref`). Confirm the dispatch publishes a branch tag, not a main tag.
