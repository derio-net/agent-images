# syntax=docker/dockerfile:1
# Pinned to ruvnet/ruflo SHA — bump deliberately when re-vendoring.
ARG RUFLO_GIT_REF=9b169814849b75bdee4b75e7d3d85a0db567802d

# --- source: clone the upstream repo at the pinned SHA. Single source of truth
#     for both the builder and runtime stages so we never drift between them.
FROM alpine/git AS source
ARG RUFLO_GIT_REF
WORKDIR /src
RUN git clone https://github.com/ruvnet/ruflo.git . \
 && git checkout "${RUFLO_GIT_REF}"

# --- builder: mirrors upstream `builder` stage in src/ruvocal/Dockerfile.
#     Full node:24 (not slim) for the Svelte build's native deps.
FROM node:24 AS builder
WORKDIR /app
COPY --from=source --chown=1000:1000 \
     /src/ruflo/src/ruvocal/package.json \
     /src/ruflo/src/ruvocal/package-lock.json \
     ./
ENV BODY_SIZE_LIMIT=15728640
RUN --mount=type=cache,target=/app/.npm \
    npm set cache /app/.npm \
 && npm ci
COPY --from=source --chown=1000:1000 /src/ruflo/src/ruvocal/ ./
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
COPY --from=source --chown=1000:1000 /src/ruflo/src/ruvocal/.env /app/.env
COPY --from=source --chown=1000:1000 /src/ruflo/src/ruvocal/entrypoint.sh /app/entrypoint.sh
COPY --from=source --chown=1000:1000 /src/ruflo/src/ruvocal/package.json /app/package.json

# Match the two seds upstream applies in its `base` stage so empty placeholder
# values don't block .env.local overrides via `dotenv-cli -c`.
RUN sed -i 's/^MODELS=$/# MODELS=/' /app/.env \
 && sed -i 's/^TASK_MODEL=$/# TASK_MODEL=/' /app/.env \
 && chmod +x /app/entrypoint.sh \
 && touch /app/.env.local \
 && chown 1000:1000 /app/.env.local /app/.env /app/entrypoint.sh /app/package.json

COPY --from=builder --chown=1000:1000 /app/build /app/build
COPY --from=builder --chown=1000:1000 /app/node_modules /app/node_modules

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:/usr/local/bin:/usr/bin:/bin \
    BODY_SIZE_LIMIT=15728640 \
    INCLUDE_DB=false

USER user
EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash", "-c", "/app/entrypoint.sh"]
