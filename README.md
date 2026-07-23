# agent-images

Shared base image and per-pod child images for secure agent pods on Frank.

## Images

| Image | Base | Purpose |
|-------|------|---------|
| `agent-base` | `debian:bookworm-slim` | Common toolchain (claude, gh, node, bun, python3, uv, supercronic) |
| `secure-agent-kali` | `agent-base` | Kali pentest tools + sshd + kubectl/talosctl/omnictl |
| `vk-local` | `agent-base` | VibeKanban local-mode server binary (from `derio-net/vibe-kanban` fork) |
| [`multi-agent-shell`](multi-agent-shell/) | `agent-shell-base` | Multi-harness shell: claude + codex + agy + opencode, implements the [multi-harness shell standard](docs/standards/multi-harness-shells.md). Second intermediate base for Phase 3 `infra-shell`. |
| [`hermes-agent-shell`](hermes-agent-shell/) | `agent-shell-base` | Single-harness shell for the `hermes` agent (BYOK against an OpenAI-compatible endpoint — the documented exception to the [standard](docs/standards/multi-harness-shells.md)'s no-API-tokens auth contract). |
| [`infra-shell`](infra-shell/) | `multi-agent-shell` | Cluster-ops shell: inherits the four multi-agent-shell harnesses and adds `kubectl`/`talosctl`/`omnictl`. No pentest packages — operators can layer via inventory `apt:` if ever needed. |

## Build

CI builds all images on every push to `main` and publishes to `ghcr.io/derio-net/`.

```
base/Dockerfile          → ghcr.io/derio-net/agent-base:<sha>
kali/Dockerfile          → ghcr.io/derio-net/secure-agent-kali:<sha>
vk-local/Dockerfile      → ghcr.io/derio-net/vk-local:<sha>
```

Children are built after base completes, inheriting the base SHA from the same commit.

The `vk-local` image also consumes `ghcr.io/derio-net/vibe-kanban-build:<fork-sha>` as a source for the compiled server binary; cross-repo builds are coordinated via `repository_dispatch` from the fork repo.

## Version audit

Nothing watches the upstream version pins in this repo, so between
hand-measurements they drift untracked. `scripts/version_audit.py` reports what
has drifted, on demand:

```bash
cd scripts && uv run python version_audit.py
uv run python version_audit.py --no-cluster   # skip the kubectl probe
```

It is a **report, not a gate** — it always exits 0, and there is deliberately no
scheduled workflow opening drift PRs.

Two things about it are worth knowing before reading its output:

- **It groups by refresh path, not by how many releases behind a pin is.**
  *Bootstrap* pins (`claude-code`, `codex`, `opencode`) are first-boot seeds
  only: the CLI self-updates in-pod and floats forward via the shell inventory's
  `harnesses:` key, so a nine-release gap there is near-meaningless. For
  *rebuild-only* pins the image rebuild is the only refresh path, so staleness
  is real.
- **"Latest" is the wrong target for two pins.** `talosctl` must track the
  **cluster's** Talos version (Talos supports only ±1 minor of client skew — in
  July 2026 the shells sat three minors behind, outside support) and `omnictl`
  must track the running **Omni server**. Both carry an anchor, and when the
  anchor can't be probed the report says `unknown` rather than falling back to
  latest — a confident wrong answer is worse than an honest gap.

Adding a version pin to a Dockerfile means adding a `PIN_SPECS` entry in
`scripts/version_audit.py`. `test_no_uncovered_version_args` fails if you don't,
which is what keeps the registry from silently under-reporting.
