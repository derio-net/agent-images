FROM debian:bookworm-slim

ARG TARGETARCH
ARG NODE_MAJOR=22
ARG SUPERCRONIC_VERSION=0.2.33

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    HOME=/home/claude \
    PATH=/home/claude/.local/bin:/usr/local/bin:/usr/bin:/bin

# ── System packages ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    adduser ca-certificates curl wget git git-lfs jq bash less \
    python3 python3-pip python3-venv pipx \
    tini gnupg2 openssh-client unzip vim-tiny procps rsync \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 22 ──
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Bun ──
RUN curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash

# ── uv (Python package manager) ──
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ── GitHub CLI ──
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# ── Claude Code CLI (bootstrap via npm; self-updates into ~/.local/bin on first run) ──
RUN npm install -g @anthropic-ai/claude-code

# ── yq (YAML processor — spec requires parity with jq) ──
RUN ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "arm64" || echo "amd64") \
    && curl -fsSL -o /usr/local/bin/yq \
      "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${ARCH}" \
    && chmod +x /usr/local/bin/yq

# ── supercronic (non-root cron replacement) ──
RUN ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "arm64" || echo "amd64") \
    && curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH}" \
    && chmod +x /usr/local/bin/supercronic

# ── Non-root user (UID/GID 1000 — matches PVC ownership) ──
RUN /usr/sbin/addgroup --gid 1000 claude \
    && /usr/sbin/adduser --uid 1000 --gid 1000 --disabled-password --gecos "" --shell /bin/bash claude

USER claude
WORKDIR /home/claude
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
