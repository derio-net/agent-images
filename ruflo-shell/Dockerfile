ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}

# Inherit AGENT_USER=agent, AGENT_HOME=/home/agent, AGENT_UID/GID=1000 from
# agent-shell-base — do not override. Fresh PV, no legacy identity to preserve.

USER root

COPY --chown=root:root rootfs/ /

RUN chmod +x \
      /etc/cont-init.d/40-shell-inventory \
      /etc/profile.d/40-ruflo-shell-paths.sh \
      /etc/profile.d/50-ruflo-shell-motd.sh \
      /etc/profile.d/60-ruflo-shell-banner.sh \
      /usr/local/lib/ruflo-shell/install-base-runtimes.sh \
      /usr/local/lib/ruflo-shell/install-inventory.sh \
      /usr/local/lib/ruflo-shell/notify-telegram.sh \
      /usr/local/lib/ruflo-shell/lib.sh \
 && /usr/local/lib/ruflo-shell/install-base-runtimes.sh \
 && npm install -g @anthropic-ai/claude-code \
 && ln -sf /usr/local/lib/ruflo-shell/install-inventory.sh \
           /usr/local/bin/ruflo-shell-reconcile

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
