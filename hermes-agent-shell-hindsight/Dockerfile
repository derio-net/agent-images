ARG BASE_SHA=latest
FROM ghcr.io/derio-net/multi-agent-shell:${BASE_SHA}

# Inherit AGENT_USER=agent, AGENT_HOME=/home/agent, AGENT_UID=1000 (ENV from
# agent-shell-base). AGENT_GID is an ARG upstream so it does not propagate —
# re-declare it for the install -o/-g substitutions below.
ARG AGENT_GID=1000

USER root

# ---------------------------------------------------------------------------
# Hindsight backend stack — the permanent, image-baked form of the stack that
# was hand-run on the migrate pod (derio-net/willikins#285). Ground-truth
# recipe extracted verbatim from the live env: PostgreSQL 18.4 + pgvector 0.8.3
# (conda-forge) and hindsight-api-slim[local-ml] 0.8.4 (public PyPI → torch-CPU
# + sentence-transformers). Baked into the IMAGE at /opt/micromamba, so a pod
# restart never loses the stack; only DATA lives on the PVC.
#
# We build FROM multi-agent-shell (not a bare micromamba base) deliberately: it
# supplies s6-overlay, the UID-1000 `agent` user, and the baked `claude` CLI +
# claude-agent-sdk that the `claude-code` Hindsight retain provider drives.
# ---------------------------------------------------------------------------
ENV MAMBA_ROOT_PREFIX=/opt/micromamba
ENV HINDSIGHT_ENV=hindsight-pg
ENV HF_HOME=/opt/hindsight-models
ARG MICROMAMBA_VERSION=2.8.1
ARG HINDSIGHT_API_VERSION=0.8.4
ARG TORCH_VERSION=2.13.0
# Pin the embedding-model revision so the baked snapshot is byte-reproducible.
ARG BGE_REVISION=5c38ec7c405ec4b44b94cc5a9bb96e735b38267a

# micromamba binary (static; extracts bin/micromamba).
RUN curl -Ls "https://micro.mamba.pm/api/micromamba/linux-64/${MICROMAMBA_VERSION}" \
      | tar -xj -C /usr/local bin/micromamba \
 && micromamba --version

# conda-forge env: python + postgresql + pgvector extension. The env matches
# the live `hindsight-pg` env; pgvector 0.8.3 provides vector.so/vector.control
# so hindsight-api's Alembic `CREATE EXTENSION vector` succeeds on first boot.
RUN micromamba create -y -n "${HINDSIGHT_ENV}" -c conda-forge \
      "python=3.11" pip "postgresql=18.4" "pgvector=0.8.3" \
 && micromamba clean -qya

# torch first, pinned to the +cpu index so the ML stack stays CPU-only (no
# multi-GB CUDA wheels) — matches the live torch==2.13.0+cpu.
RUN micromamba run -n "${HINDSIGHT_ENV}" pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}"

# hindsight-api-slim with the local-ml extra (sentence-transformers, onnxruntime,
# etc.). torch is already satisfied above; the cpu extra-index keeps any
# transitive torch resolution CPU-only.
RUN micromamba run -n "${HINDSIGHT_ENV}" pip install --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      "hindsight-api-slim[local-ml]==${HINDSIGHT_API_VERSION}" \
 && micromamba run -n "${HINDSIGHT_ENV}" hindsight-api --help >/dev/null

# Pre-bake the embedding model into a fixed LOCAL dir (not the hub cache) so the
# API loads it offline, on CPU, BY PATH — bypassing hub refs/revision resolution.
# A revision-pinned snapshot_download populates snapshots/<hash>/ but writes no
# refs/main, so loading by repo-id offline (SentenceTransformer's default `main`
# revision) fails "not in cached files". local_dir + a path-valued model env
# sidesteps that entirely while keeping the revision pin.
RUN micromamba run -n "${HINDSIGHT_ENV}" python -c \
      "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-en-v1.5', revision='${BGE_REVISION}', local_dir='/opt/hindsight-models/bge-small-en-v1.5')"

# The baked stack must be readable/executable by UID 1000 (the runtime user);
# the env is immutable at runtime, all mutable state is on the PVC.
RUN chown -R ${AGENT_UID}:${AGENT_GID} /opt/micromamba /opt/hindsight-models

COPY --chown=root:root rootfs/ /

# Strip ALL inherited agent-shell scaffolding — this is a headless Hindsight
# backend, not an interactive shell. The base's cont-init.d/services.d assume a
# writable MOUNTED $HOME (ssh host/authorized keys, a uv venv for cron
# heartbeats, native-harness/claude installs, shell inventory, supercronic) and
# hard-fail here: $HOME is an unmounted image dir (only /opt/hindsight is a PVC).
# Keep ONLY our own 30-hindsight-initdb cont-init and the postgres/hindsight-api
# longruns. (sshd would also collide with the main ssh-sidecar on :2222 in the
# shared pod netns; the claude CLI *binary* stays on PATH for claude-code retain
# — only the runtime init scripts go.)
RUN rm -rf \
      /etc/services.d/sshd \
      /etc/services.d/supercronic \
      /etc/services.d/agent-session-server \
      /etc/cont-init.d/00-run-agent-init \
      /etc/cont-init.d/10-ssh-host-keys \
      /etc/cont-init.d/20-venv \
      /etc/cont-init.d/30-authorized-keys \
      /etc/cont-init.d/40-skel \
      /etc/cont-init.d/40-shell-inventory \
      /etc/cont-init.d/45-native-harnesses \
      /etc/cont-init.d/46-agent-instructions

# $HOME must be writable by UID 1000: our initdb + service run scripts call
# `micromamba run`, which acquires a proc-lock under the XDG cache. $HOME is an
# unmounted image dir here, so redirect the cache to a writable in-image path
# (the CrashLoop was `micromamba run` failing to lock $HOME/.cache/mamba/proc)
# and chown $HOME as belt-and-suspenders.
ENV XDG_CACHE_HOME=/opt/hindsight-cache
RUN install -d -o ${AGENT_UID} -g ${AGENT_GID} -m 0755 /opt/hindsight-cache \
 && chown -R ${AGENT_UID}:${AGENT_GID} /home/agent

# Stable hindsight-api settings (pydantic-settings env). LLM/retain provider
# vars are set by the frank manifest (claude-code), NOT baked here, so the
# image is provider-agnostic.
# The embedding model is a PATH (the baked local_dir), not a repo-id, so it
# loads offline without hub resolution. HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE make
# the sidecar strictly self-contained (no accidental huggingface.co fetch).
ENV HINDSIGHT_API_DATABASE_URL=postgresql://hindsight:hindsight@127.0.0.1:5433/postgres \
    HINDSIGHT_API_EMBEDDINGS_PROVIDER=local \
    HINDSIGHT_API_EMBEDDINGS_LOCAL_MODEL=/opt/hindsight-models/bge-small-en-v1.5 \
    HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU=true \
    HINDSIGHT_API_RERANKER_PROVIDER=rrf \
    HINDSIGHT_PGDATA=/opt/hindsight/pgdata \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Pre-create the PVC mount point (UID 1000 owned so initdb can write once
# fsGroup makes the mounted volume group-writable) and make the s6 scripts
# executable — under K8s the agent UID cannot chmod root-owned files at runtime.
RUN install -d -o ${AGENT_UID} -g ${AGENT_GID} -m 0755 /opt/hindsight \
 && chmod +x \
      /etc/cont-init.d/30-hindsight-initdb \
      /etc/services.d/postgres/run \
      /etc/services.d/hindsight-api/run

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 8888
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
