# syntax=docker/dockerfile:1
# Pinned to ruvnet/ruflo SHA — bump deliberately when re-vendoring.
# Re-vendored a6dd4ab -> 26c35b5 (2026-07-23).
#
# "607 commits behind" is a MONOREPO artifact - we build only the
# ruflo/src/ruvocal subtree. Measured there by tree/blob SHA: 501 blobs at both
# refs, no paths added or removed, exactly ONE changed file
# (mcp-bridge/index.js). Do NOT measure this with the compare API: its
# .files[] caps at 300 entries and reports a false "no ruvocal changes".
#
# That one file is ADR-166 security hardening closing a disclosed
# UNAUTHENTICATED RCE chain: terminal_execute-family tools are now deny-by-
# default (MCP_ENABLE_TERMINAL opt-in), the bridge binds 127.0.0.1 instead of
# every interface, it refuses to bind a public interface without
# MCP_AUTH_TOKEN, bearer auth uses timingSafeEqual, and CORS is an allowlist
# rather than an unconditional "*". mcp-bridge is not shipped in our runtime
# stage, so this is close to a functional no-op for the deployed artifact - it
# removes a known-vulnerable file from the build context.
#
# Both local modifications below still apply: their targets are byte-identical
# across the range, and upstream PR ruvnet/ruflo#2293 is still OPEN.
ARG RUFLO_GIT_REF=26c35b59b40a0a95b286ccf5ac675a15edcc995f

# --- source: shallow-clone the upstream repo at the pinned SHA. Single source
#     of truth for both the builder and runtime stages so we never drift.
#     `git init` + `git fetch --depth 1 <SHA>` is the only shape that works for
#     a SHA-pinned shallow clone (`git clone --depth 1 <url>` without a branch
#     ref-spec doesn't accept arbitrary SHAs). Saves ~100 MB vs a full clone.
#     node:24 ships git, so we don't need a separate alpine/git stage.
FROM node:24 AS source
ARG RUFLO_GIT_REF
# Pinned URL of the last commit where ruflo/src/ruvocal/.env was tracked.
# Upstream removed `.env` from the index on 2026-05-05 in ruvnet/ruflo@f8f4cd4
# ("security: untrack .env files + broaden .gitignore to block .env.*") because
# the file historically contained admin tokens. Their commit message states
# "Files remain on disk for local development; only removed from the index" —
# i.e. the file is still load-bearing at build time, just not distributed via
# the repo. Their own Dockerfile still `COPY .env /app/.env`s it; cloudbuild
# provides it out-of-band. We mirror that pattern by pulling the content from
# the parent commit `0fd61e3e5b20` (f8f4cd4^), which is the last SHA where it
# was tracked. The 8047-byte payload is chat-ui defaults only — feature flags,
# OIDC scopes, MCP toggles, `MODELS=`, `TASK_MODEL=`, rate-limit thresholds.
# All sensitive values (OPENAI_API_KEY, DATABASE_URL, etc.) are injected at
# runtime via the Kubernetes Deployment's envFrom secretRef + envVar blocks;
# nothing secret rides on this defaults file.
ARG RUFLO_ENV_FALLBACK_SHA=0fd61e3e5b203282e018258fa8a80e56f30db295
WORKDIR /src/ruflo
RUN git init \
 && git remote add origin https://github.com/ruvnet/ruflo.git \
 && git fetch --depth 1 origin "${RUFLO_GIT_REF}" \
 && git checkout FETCH_HEAD \
 && if [ ! -s ruflo/src/ruvocal/.env ]; then \
      curl -fsSL "https://raw.githubusercontent.com/ruvnet/ruflo/${RUFLO_ENV_FALLBACK_SHA}/ruflo/src/ruvocal/.env" \
        -o ruflo/src/ruvocal/.env \
      && test -s ruflo/src/ruvocal/.env; \
    fi
# Upstream's tree has the actual sveltekit app at `ruflo/src/ruvocal/`
# (note the extra leading `ruflo/` — the repo's top-level dir mirrors the
# org name). The plan's Deployment Notes flagged this as a path correction;
# this Dockerfile honours it: every COPY below uses
# /src/ruflo/ruflo/src/ruvocal/... not /src/ruflo/src/ruvocal/...
#
# Patch upstream's URL safety guard to accept the browser-local WASM MCP.
#
# Upstream `isValidUrl()` only allows http/https against safe hostnames,
# which is correct for HTTP MCP servers (SSRF prevention). But ruvocal also
# ships an in-browser WASM MCP server ("RVAgent Local") whose URL is
# `wasm://local` — the server never reaches this URL, the browser hosts the
# WebAssembly agent itself. Rejecting it at the server-side safety guard
# leaves users with autopilot ON + only-WASM-MCP selected unable to chat:
# `runMcpFlow` strips the rejected server, sees zero valid tools, and the
# chat-ui SPA silently refuses to submit. Allow `wasm:` early-return so the
# guard treats it as out-of-scope rather than unsafe.
#
# Symptom verified live on derio-net/frank ruflo deployment 2026-05-16:
# with autopilot ON, the SPA silently refused to submit; toggling autopilot
# OFF (which bypasses the MCP/tools code path entirely) allowed chat to
# proceed against local LiteLLM models. This patch removes the autopilot
# precondition for fresh deployments that don't ship server-side MCP_SERVERS.
# Filed upstream as ruvnet/ruflo#2293, which is still OPEN (not merged) -
# so this patch remains REQUIRED. Re-verified at the pinned ref 2026-07-23.
RUN sed -i \
      -e 's|const hostname = url\.hostname\.toLowerCase();|if (url.protocol === "wasm:") return true;\n\t\tconst hostname = url.hostname.toLowerCase();|' \
      ruflo/src/ruvocal/src/lib/server/urlSafety.ts \
 && grep -q 'protocol === "wasm:"' ruflo/src/ruvocal/src/lib/server/urlSafety.ts

# Repair the RvfGridFSBucket GridFS shim so file upload/download/copy work
# against the RVF backend.
#
# ruvocal is hardcoded to the RVF storage backend, whose RvfGridFSBucket only
# *mimics* MongoDB's GridFSBucket API — incompletely. The Mongo-era chat-ui
# callers expect real streams/cursors:
#   - uploadFile.ts  : upload.once("finish"/"error", …)  → needs a Writable
#                      (and passes an ArrayBuffer, which a default Writable
#                      rejects — the objectMode shim coerces it)
#   - downloadFile.ts: openDownloadStream(...).on("data"/"end"/"error")  → needs
#                      a Readable; bucket.find(...).next()  → needs a sync cursor
#   - conversation.ts: openDownloadStream(...).pipe(uploadStream)  → needs both
# The upstream shim returns plain objects, so every file upload 500s with
# `TypeError: upload.once is not a function` and reads/copies fail too. The patch
# makes the shim faithfully honor the GridFS contract (real Writable via
# objectMode, real Readable via Readable.from, sync find cursor). Verified to
# apply cleanly at this pinned RUFLO_GIT_REF; the grep guards fail the build if
# the patch silently no-ops after a future bump. Filed upstream as
# ruvnet/ruflo#2293, still OPEN (not merged) - upstream HEAD carries none of
# `new Writable` / `Readable.from` / `next: async`, so this stays REQUIRED.
COPY patches/rvf-gridfs-parity.patch /tmp/rvf-gridfs-parity.patch
RUN git apply /tmp/rvf-gridfs-parity.patch \
 && grep -q 'new Writable'  ruflo/src/ruvocal/src/lib/server/database/rvf.ts \
 && grep -q 'Readable.from' ruflo/src/ruvocal/src/lib/server/database/rvf.ts \
 && grep -q 'next: async'   ruflo/src/ruvocal/src/lib/server/database/rvf.ts

# --- builder: mirrors upstream `builder` stage in src/ruvocal/Dockerfile.
#     Full node:24 (not slim) for the Svelte build's native deps.
FROM node:24 AS builder
WORKDIR /app
COPY --from=source --chown=1000:1000 \
     /src/ruflo/ruflo/src/ruvocal/package.json \
     /src/ruflo/ruflo/src/ruvocal/package-lock.json \
     ./
ENV BODY_SIZE_LIMIT=15728640
RUN --mount=type=cache,target=/app/.npm \
    npm set cache /app/.npm \
 && npm ci
COPY --from=source --chown=1000:1000 /src/ruflo/ruflo/src/ruvocal/ ./
# `git config safe.directory /app` is mirrored from upstream's Dockerfile (their
# build context is `src/ruvocal/` so they have no `.git` either — the line is a
# defensive no-op for any sveltekit plugin that probes for git metadata).
# `npm run build` prerenders pages that fetch the HuggingFace router model
# list (router.huggingface.co) at build time. A momentary HF 429 otherwise
# fails the whole build — and matrix fail-fast then cancels the sibling images
# (agent-images#115). Retry with linear backoff so a transient upstream
# rate-limit doesn't break a build whose own sources are fine.
RUN git config --global --add safe.directory /app \
 && for attempt in 1 2 3 4 5; do \
      npm run build && break; \
      status=$?; \
      if [ "$attempt" -eq 5 ]; then \
        echo "npm run build failed after 5 attempts (last exit $status)" >&2; \
        exit "$status"; \
      fi; \
      delay=$((attempt * 15)); \
      echo "npm run build failed (attempt $attempt/5, exit $status); retrying in ${delay}s…" >&2; \
      sleep "$delay"; \
    done

# --- runtime: mirrors upstream `base` + `final` (INCLUDE_DB=false branch).
#     The `local_db_true` Mongo install layer is intentionally omitted; ruvocal
#     connects to an external database via DATABASE_URL (Postgres) or the legacy
#     MONGO_URL env var (kept by upstream for backwards compat).
FROM node:24-slim AS runtime
RUN npm install -g dotenv-cli \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl dnsutils libcurl4 libgomp1 tini \
 && rm -rf /var/lib/apt/lists/* \
 && userdel -r node \
 && useradd -m -u 1000 user \
 && mkdir -p /home/user/.npm /app /app/db \
 && chown -R 1000:1000 /home/user/.npm /app

# /app needs to be writable to UID 1000: ruvocal's startup code path runs
# `Database.init` which unconditionally `mkdir`s `/app/db` (regardless of
# INCLUDE_DB), so the directory itself must be owned by user. Upstream's
# Dockerfile gets this for free because their WORKDIR runs after `USER user`;
# our multi-stage build creates /app while still root, so we chown above.
WORKDIR /app
COPY --from=source --chown=1000:1000 /src/ruflo/ruflo/src/ruvocal/.env /app/.env
COPY --from=source --chown=1000:1000 /src/ruflo/ruflo/src/ruvocal/entrypoint.sh /app/entrypoint.sh
COPY --from=source --chown=1000:1000 /src/ruflo/ruflo/src/ruvocal/package.json /app/package.json

# Match the two seds upstream applies in its `base` stage so empty placeholder
# values don't block .env.local overrides via `dotenv-cli -c`.
RUN sed -i 's/^MODELS=$/# MODELS=/' /app/.env \
 && sed -i 's/^TASK_MODEL=$/# TASK_MODEL=/' /app/.env \
 && chmod +x /app/entrypoint.sh \
 && touch /app/.env.local \
 && chown 1000:1000 /app/.env.local /app/.env /app/entrypoint.sh /app/package.json

COPY --from=builder --chown=1000:1000 /app/build /app/build
COPY --from=builder --chown=1000:1000 /app/node_modules /app/node_modules

# Mirror upstream's `ENV PATH=/home/user/.local/bin:$PATH` shape so we keep
# /usr/local/sbin:/usr/sbin:/sbin from the inherited node-image PATH (some
# native node modules call sbin tools at runtime).
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    BODY_SIZE_LIMIT=15728640 \
    INCLUDE_DB=false

USER user
EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash", "-c", "/app/entrypoint.sh"]
