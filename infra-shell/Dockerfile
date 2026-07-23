ARG BASE_SHA=latest
FROM ghcr.io/derio-net/multi-agent-shell:${BASE_SHA}

# Inherit AGENT_USER=agent, AGENT_HOME=/home/agent, AGENT_UID=1000 from
# agent-shell-base via its ENV line — do not override.
#
# AGENT_GID is set as ARG (not ENV) in agent-shell-base, so it does not
# propagate to child images. Re-declare for the install -d below.
ARG AGENT_GID=1000

USER root

# ── Cluster-admin tooling (kubectl, talosctl, omnictl) ──
# Pins + install method copied verbatim from kali/Dockerfile so the two
# images stay byte-comparable for the tools they share. kubectl uses the
# k8s.io stable.txt redirect (unpinned); talosctl/omnictl carry explicit
# version pins. Pentest packages (nmap, kali-tools-top10, etc.) are
# intentionally NOT included — infra-shell is cluster-ops only.
ARG TARGETARCH
# talosctl tracks the CLUSTER's Talos version (measured v1.12.6, 2026-07-23) -
# NOT the newest upstream release (v1.13.7 at time of writing). Talos supports
# only +/-1 minor of client skew, and this pin had drifted three minors behind
# (v1.9.5) with no alert and no symptom until a command needed the newer API.
# Pinning to "latest" instead would put the client AHEAD of the nodes and
# re-create the same skew the moment the cluster lags.
# Guarded by scripts/tests/test_talosctl_pin_parity.py against
# LAST_MEASURED_CLUSTER_TALOS in scripts/version_audit.py.
ARG TALOSCTL_VERSION=v1.12.6
ARG OMNICTL_VERSION=v0.45.1
RUN curl -fsSL -o /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${TARGETARCH}/kubectl" \
    && chmod +x /usr/local/bin/kubectl
RUN curl -fsSL -o /usr/local/bin/talosctl \
      "https://github.com/siderolabs/talos/releases/download/${TALOSCTL_VERSION}/talosctl-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/talosctl
RUN curl -fsSL -o /usr/local/bin/omnictl \
      "https://github.com/siderolabs/omni/releases/download/${OMNICTL_VERSION}/omnictl-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/omnictl

COPY --chown=root:root rootfs/ /

# Pre-create the dirs the inventory installer writes to. Mirrors
# multi-agent-shell's setup: under K8s (runAsUser: 1000, cap-drop=ALL) the
# agent UID cannot create root-owned directories at runtime, and
# agent-shell-base only chowns /run + /var/run. Without these,
# install-inventory.sh's tee + motd write fail silently inside cont-init.d.
# /var/log/cont-init.d already exists from the multi-agent-shell layer;
# re-running install -d is idempotent.
RUN install -d -o ${AGENT_UID} -g ${AGENT_GID} -m 0755 \
      /var/log/cont-init.d \
      /var/lib/infra-shell \
 && chmod +x \
      /etc/cont-init.d/40-shell-inventory \
      /etc/profile.d/40-infra-shell-paths.sh \
      /etc/profile.d/45-infra-shell-reconcile-motd.sh \
      /etc/profile.d/50-infra-shell-motd.sh \
      /usr/local/lib/infra-shell/install-inventory.sh \
      /usr/local/lib/infra-shell/notify-telegram.sh \
      /usr/local/lib/infra-shell/lib.sh \
 && ln -sf /usr/local/lib/infra-shell/install-inventory.sh \
           /usr/local/bin/infra-shell-reconcile

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
