ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}

# Inherit AGENT_USER=agent, AGENT_HOME=/home/agent, AGENT_UID=1000 from
# agent-shell-base via its ENV line — do not override.
#
# AGENT_GID is set as ARG (not ENV) in agent-shell-base, so it does not
# propagate to child images. Re-declare it here so Docker substitutes it at
# build time in the RUN below; without this, ${AGENT_GID} expands to empty
# in /bin/sh and `install -d -o 1000 -g  -m 0755` fails (-m read as group).
ARG AGENT_GID=1000

USER root

COPY --chown=root:root rootfs/ /

# Pre-create the dirs the inventory installer writes to. Under K8s
# (runAsUser: 1000, cap-drop=ALL, allowPrivilegeEscalation: false) the agent
# UID cannot create root-owned directories at runtime, and agent-shell-base
# only chowns /run + /var/run. Without these, install-inventory.sh's tee +
# motd write fail silently inside cont-init.d, the installer appears to
# "succeed" (fail-open exit 0), and the operator gets no log and no MOTD.
RUN install -d -o ${AGENT_UID} -g ${AGENT_GID} -m 0755 \
      /var/log/cont-init.d \
      /var/lib/paperclip-shell \
 && chmod +x \
      /etc/cont-init.d/40-shell-inventory \
      /etc/profile.d/40-paperclip-shell-paths.sh \
      /etc/profile.d/50-paperclip-shell-motd.sh \
      /usr/local/lib/paperclip-shell/install-base-runtimes.sh \
      /usr/local/lib/paperclip-shell/install-inventory.sh \
      /usr/local/lib/paperclip-shell/notify-telegram.sh \
      /usr/local/lib/paperclip-shell/lib.sh \
 && /usr/local/lib/paperclip-shell/install-base-runtimes.sh \
 && ln -sf /usr/local/lib/paperclip-shell/install-inventory.sh \
           /usr/local/bin/paperclip-shell-reconcile

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
