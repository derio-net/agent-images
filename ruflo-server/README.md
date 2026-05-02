# ruflo-server

Container image for the ruvocal web UI + swarm orchestrator from
[`ruvnet/ruflo`](https://github.com/ruvnet/ruflo) (the rebrand of `claude-flow`).
Deployed on Frank as the long-lived service half of the `ruflo` pod, paired
with [`ruflo-shell`](../ruflo-shell/) as an SSH-able sidecar.

## Build

`Dockerfile` thin-wraps the upstream `ruflo/src/ruvocal/Dockerfile` at a pinned
git SHA. The `INCLUDE_DB=false` build path is used unconditionally — the Mongo
install layer is omitted from the final image. Database state lives in a
separate sub-app (`apps/ruflo-db/` in `derio-net/frank`).

| Build arg | Default | Notes |
|---|---|---|
| `RUFLO_GIT_REF` | pinned SHA | Bump deliberately to re-vendor upstream. CI does **not** float this; pinning is intentional so an upstream change can't silently land in our cluster. |

## Runtime expectations

The image runs `dotenv -e /app/.env -c -- node ... /app/build/index.js
--host 0.0.0.0 --port 3000`. It honours these env vars (most via
`.env.local`-style override; see upstream `.env` for the full list):

| Env | Purpose | Source on Frank |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string for ruvocal's persistent store | `apps/ruflo-db/` (Phase 2+) |
| `OPENAI_BASE_URL` | OpenAI-compatible inference endpoint | LiteLLM gateway: `http://litellm.litellm-system:4000` |
| `OPENAI_API_KEY` | Token for the inference endpoint | ESO → Infisical |
| `OPENROUTER_API_KEY` | Direct OpenRouter access (broader catalog) | ESO → Infisical |
| `EMAIL_RESEND_API_KEY` | Transactional email from agent runs | ESO → Infisical (shared with paperclip) |

The legacy `MONGO_URL`/`MONGODB_URL` env vars are still honoured by upstream
for backwards compatibility but are noted as unused in the upstream `.env`.

The web UI listens on **3000/TCP**. Workspace data is expected at `/app` (the
operator-facing `/workspace` mount in the pod spec is shared with `ruflo-shell`
for ergonomic browsing — ruvocal itself writes its agent-run artefacts under
`/app/build` and the DB volume).

## Plan / spec

- Spec: `docs/superpowers/specs/2026-05-02--orch--ruflo-pod-design.md` (`derio-net/frank`)
- Plan: `docs/superpowers/plans/2026-05-02--orch--ruflo-pod.md` (`derio-net/frank`)

## CI

Built by `.github/workflows/build.yaml` on every push to `main`, tagged
`ghcr.io/derio-net/ruflo-server:<sha>` and `:latest`. Smoke test verifies the
container boots and listens on port 3000.
