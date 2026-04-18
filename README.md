# agent-images

Shared base image and per-pod child images for secure agent pods on Frank.

## Images

| Image | Base | Purpose |
|-------|------|---------|
| `agent-base` | `debian:bookworm-slim` | Common toolchain (claude, gh, node, bun, python3, uv, supercronic) |
| `secure-agent-kali` | `agent-base` | Kali pentest tools + sshd + kubectl/talosctl/omnictl |
| `vk-local` | `agent-base` | VibeKanban local-mode server binary (from `derio-net/vibe-kanban` fork) |

## Build

CI builds all images on every push to `main` and publishes to `ghcr.io/derio-net/`.

```
base/Dockerfile          → ghcr.io/derio-net/agent-base:<sha>
kali/Dockerfile          → ghcr.io/derio-net/secure-agent-kali:<sha>
vk-local/Dockerfile      → ghcr.io/derio-net/vk-local:<sha>
```

Children are built after base completes, inheriting the base SHA from the same commit.

The `vk-local` image also consumes `ghcr.io/derio-net/vibe-kanban-build:<fork-sha>` as a source for the compiled server binary; cross-repo builds are coordinated via `repository_dispatch` from the fork repo.
