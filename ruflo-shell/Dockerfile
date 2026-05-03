ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}

# Inherit AGENT_USER=agent, AGENT_HOME=/home/agent, AGENT_UID/GID=1000 from
# agent-shell-base — do not override. Fresh PV, no legacy identity to preserve.

USER root

COPY --chown=root:root rootfs/ /

# Pre-create the dirs the inventory installer writes to. Under K8s
# (runAsUser: 1000, cap-drop=ALL, allowPrivilegeEscalation: false) the agent
# UID cannot create root-owned directories at runtime, and agent-shell-base
# only chowns /run + /var/run. Without these, install-inventory.sh's tee +
# motd write fail with EACCES inside cont-init.d. Mirrors paperclip-shell's
# Dockerfile — kept in sync between the two shell images by convention.
ARG AGENT_GID=1000
RUN install -d -o ${AGENT_UID} -g ${AGENT_GID} -m 0755 \
      /var/log/cont-init.d \
      /var/lib/ruflo-shell \
 && chmod +x \
      /etc/cont-init.d/40-shell-inventory \
      /etc/profile.d/40-ruflo-shell-paths.sh \
      /etc/profile.d/50-ruflo-shell-motd.sh \
      /etc/profile.d/60-ruflo-shell-banner.sh \
      /usr/local/lib/ruflo-shell/install-base-runtimes.sh \
      /usr/local/lib/ruflo-shell/install-inventory.sh \
      /usr/local/lib/ruflo-shell/notify-telegram.sh \
      /usr/local/lib/ruflo-shell/lib.sh \
 && /usr/local/lib/ruflo-shell/install-base-runtimes.sh \
 && ln -sf /usr/local/lib/ruflo-shell/install-inventory.sh \
           /usr/local/bin/ruflo-shell-reconcile

# `claude` is already npm-installed globally by the great-grandparent image
# (`agent-base/Dockerfile`, line 40 — `npm install -g @anthropic-ai/claude-code`).
# The smoke test for this image asserts `claude --version` runs as the agent
# UID, which catches any future agent-base regression that drops it.

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
