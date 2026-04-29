ARG AGENT_BASE_SHA=latest
ARG VK_FORK_SHA=latest

FROM ghcr.io/derio-net/vibe-kanban-build:${VK_FORK_SHA} AS vk-artifact

FROM ghcr.io/derio-net/agent-base:${AGENT_BASE_SHA}

USER root

# kubectl + talosctl (duplicated with kali — see spec for promotion policy)
RUN curl -fsSL -o /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl
RUN curl -fsSL -o /usr/local/bin/talosctl \
      https://github.com/siderolabs/talos/releases/latest/download/talosctl-linux-amd64 \
    && chmod +x /usr/local/bin/talosctl

COPY --from=vk-artifact /server /usr/local/bin/vibe-kanban
RUN chmod +x /usr/local/bin/vibe-kanban \
    && chown claude:claude /usr/local/bin/vibe-kanban

COPY entrypoint-vk-local.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER claude
WORKDIR /home/claude

EXPOSE 8081
# Wrapper runs as USER claude (non-root); /opt/agent-init.d/* scripts must be
# non-root-safe. vibe-kanban exec-replaces the wrapper, so K8s supervises it
# directly under tini PID 1 — no s6, no extra supervisor layer.
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
