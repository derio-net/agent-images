# hermes-agent-shell-hindsight

The **Hindsight memory sidecar** for the `hermes-agent-shell` pod on Frank
(`derio-net/willikins#285`). It runs the Hindsight backend — PostgreSQL 18.4 +
`hindsight-api-slim` — as a dedicated, k8s-supervised container alongside the
bare official `nousresearch/hermes-agent` main container. Hermes reaches it in
`local_external` mode over the shared pod loopback (`127.0.0.1:8888`), exactly
as it did when the backend was hand-run inside the old custom image — but now
supervised by s6, isolated on its own PVC, and running strict non-root.

## Why a sidecar

The official Hermes image ships only the Hindsight *client*; it has no embedded
backend (no `hindsight_embed`, no Postgres, no torch). The permanent design puts
the backend in this separate image so the main container stays the unmodified
official image, k8s supervises the backend (no in-pod watchdog), Postgres gets a
clean non-root `securityContext` (impossible in the root-bound main container),
and the memory volume — isolated on its own PVC — auto-joins Longhorn's existing
backup group. See the design spec in willikins:
`docs/superpowers/specs/2026-07-09-hermes-official-migration-design.md`.

## Stack (ground-truth recipe, willikins#285)

Built `FROM ghcr.io/derio-net/multi-agent-shell` — inherits s6-overlay, the
UID-1000 `agent` user, and the baked `claude`/`codex` CLIs used by the
`claude-code` retain provider. On top:

- **micromamba env `hindsight-pg`** (baked into the image, not the PVC):
  `postgresql=18.4` + `hindsight-api-slim[local-ml]==0.8.4` (public PyPI) →
  torch-CPU + sentence-transformers.
- **`BAAI/bge-small-en-v1.5`** pre-baked into the image HF cache (offline, CPU).
- **s6 longruns**: `postgres` (loopback `:5433`) and `hindsight-api` (`:8888`),
  `hindsight-api` gated on `pg_isready`.
- **sshd disabled** — the base bakes an sshd on `:2222`, which would collide
  with the main pod's ssh-sidecar in the shared netns.

## Data vs. image

- **Image** carries the *stack* (binaries, Python env, embedding model).
- **PVC** (`hermes-agent-shell-hindsight`, mounted at `/opt/hindsight`) carries
  only *data*: `PGDATA=/opt/hindsight/pgdata`. A fresh volume is `initdb`'d by
  `cont-init.d/30-hindsight-initdb` (locale `C.UTF-8`, role `hindsight`, db
  `postgres`); production data is `pg_restore`d on top during migration.

## Retain

Recall works with no LLM. Retain (writing new memories) uses
`HINDSIGHT_API_LLM_PROVIDER=claude-code` (set by the frank manifest, Sonnet),
reusing the pre-migration provider. Left wired-dark until the model var is
confirmed; recall is unaffected.

## Smoke test

CI (`.github/workflows/build.yaml`) boots the image under the live K8s-equivalent
`securityContext` and asserts: s6 brings both services up, Postgres accepts
connections, `hindsight-api` `/health` returns `healthy`, and the embedding
model loads offline.
