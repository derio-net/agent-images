# v2 bridge cutover — agent-images side

**Spec (cross-repo):**
`derio-net/superpowers-for-vk:docs/superpowers/specs/2026-05-17-v2-bridge-
rebuild-design.md` (merged in
[derio-net/superpowers-for-vk#150](https://github.com/derio-net/superpowers-for-vk/pull/150)).

**Tracking issue:**
[derio-net/superpowers-for-vk#147](https://github.com/derio-net/superpowers-for-vk/issues/147).

## Cross-plan dependency

This plan **cannot start** until
`derio-net/superpowers-for-vk:docs/superpowers/plans/2026-05-17-v2-bridge-
rebuild/` ships all six phases and the `v2.2.0` tag is published. Phase 6 of
that plan is the gate.

Operational check before starting:

```bash
git ls-remote --tags https://github.com/derio-net/superpowers-for-vk.git \
  | grep -E 'refs/tags/v2\.2\.0'
```

If empty, this plan is blocked. Wait for the tag.

## What this plan delivers

One phase, four tasks. After this plan ships, the agent-images repo has:

- **Deleted:** `kali/scripts/vk-issue-bridge.py` (1089 LOC) and
  `kali/scripts/vk_mcp_client.py` (194 LOC).
- **Modified:** `kali/Dockerfile` — venv install pin bumped from
  `vk@v2.1.4` → `vk@v2.2.0`.
- **Modified:** `kali/config-templates/crontab.txt` — bridge line points at
  the wrapper installed by `vk install.sh --install-bridge`.
- **Modified:** `kali/etc/cont-init.d/` (or wherever container init lives) —
  invokes `install.sh --install-bridge` so the wrapper is present at
  container start.
- **Added:** `kali/tests/test_bridge_smoke.py` (F3) — `docker run` smoke
  test for `python -m vk.bridge --dry-run`.

PEP 668 venv pattern is unchanged. Node.js / npx / vibe-kanban still come
from the container image. Only the Python bridge implementation moves.

## Why single-phase

The deletions, Dockerfile bump, crontab edit, and smoke test are tightly
coupled. Splitting them would leave the image in a partially-broken state
between PRs (e.g. legacy bridge deleted but cron still calls it). One PR is
the safe atomic shape.

## Out of scope

- Changes to other kali scripts (audit, exercise, guardrails, push-heartbeat,
  session-manager, wrap-claude) — unrelated.
- Container init script overhaul. Touching it for `--install-bridge`
  invocation only; broader refactor is a separate concern.
- Pruning unused env vars from the kali Dockerfile (`VIBE_BACKEND_URL`,
  `MAX_CONCURRENT`, etc. — those stay; the bridge still reads them).
