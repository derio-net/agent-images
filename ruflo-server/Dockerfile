# syntax=docker/dockerfile:1
# Pinned to ruvnet/ruflo SHA — bump deliberately when re-vendoring.
ARG RUFLO_GIT_REF=9b169814849b75bdee4b75e7d3d85a0db567802d

# --- source: shallow-clone the upstream repo at the pinned SHA. Single source
#     of truth for both the builder and runtime stages so we never drift.
#     `git init` + `git fetch --depth 1 <SHA>` is the only shape that works for
#     a SHA-pinned shallow clone (`git clone --depth 1 <url>` without a branch
#     ref-spec doesn't accept arbitrary SHAs). Saves ~100 MB vs a full clone.
#     node:24 ships git, so we don't need a separate alpine/git stage.
FROM node:24 AS source
ARG RUFLO_GIT_REF
WORKDIR /src/ruflo
RUN git init \
 && git remote add origin https://github.com/ruvnet/ruflo.git \
 && git fetch --depth 1 origin "${RUFLO_GIT_REF}" \
 && git checkout FETCH_HEAD
# Upstream's tree has the actual sveltekit app at `ruflo/src/ruvocal/`
# (note the extra leading `ruflo/` — the repo's top-level dir mirrors the
# org name). The plan's Deployment Notes flagged this as a path correction;
# this Dockerfile honours it: every COPY below uses
# /src/ruflo/ruflo/src/ruvocal/... not /src/ruflo/src/ruvocal/...
#
# Patch upstream's ChatWindow.svelte: the pinned SHA introduces a
# `let x = $derived<T>(() => { ... }())` IIFE that vite-plugin-svelte's
# parser rejects with `js_parse_error` (the `<T>(()=>{...}())` shape
# confuses generic-vs-comparison disambiguation). Convert to the
# semantically-equivalent `$derived.by<T>(() => { ... })` form. Tracked
# upstream as ruvnet/ruflo (no issue filed — apply locally for now).
RUN sed -i \
      -e 's/let lastAssistantToolNames = \$derived<string\[\]>(() => {/let lastAssistantToolNames = \$derived.by<string[]>(() => {/' \
      -e '0,/^\t}());$/{s/^\t}());$/\t});/}' \
      ruflo/src/ruvocal/src/lib/components/chat/ChatWindow.svelte \
 && grep -q '\$derived.by<string\[\]>' ruflo/src/ruvocal/src/lib/components/chat/ChatWindow.svelte \
 && ! grep -q '^\t}());$' ruflo/src/ruvocal/src/lib/components/chat/ChatWindow.svelte

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
RUN git config --global --add safe.directory /app \
 && npm run build

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
 && mkdir -p /home/user/.npm \
 && chown -R 1000:1000 /home/user/.npm

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
