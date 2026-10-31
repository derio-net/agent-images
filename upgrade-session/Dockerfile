ARG AGENT_BASE_SHA=latest
FROM ghcr.io/derio-net/agent-base:${AGENT_BASE_SHA}

# upgrade-session - the disposable pod image behind the frank update console's
# "Start session" (frank spec 2026-10-31--life--update-security-lifecycle,
# Part 3). One pod per upgrade, deleted when the upgrade ends.
#
# Base: agent-base, NOT infra-shell. infra-shell inherits s6-overlay /init,
# sshd and the agent-session server; s6 needs a writable /run and its cont-init
# scripts write under /var/log and /var/lib, which defeats a read-only root FS,
# and a session is attached through runs-fr, not SSH. agent-base is already
# tini + non-root uid 1000 with node, python, gh and the claude CLI.
#
# Runtime contract (set by frank's pod spec, not by this image):
#   - runAsUser 1000, capabilities.drop ALL, readOnlyRootFilesystem true
#   - emptyDir at /home/claude (HOME) and /tmp - the ONLY writable paths
#   - no secrets baked in; credentials are injected per upgrade type
#   - agent instruction files (AGENTS.md / CLAUDE.md) are mounted by frank at
#     runtime; nothing here relies on skill files, which no harness loads
#
# Nothing is baked under /home/claude: the emptyDir mount hides it.

ARG TARGETARCH

USER root

# -- Cluster-admin clients, side by side ------------------------------------
# Talos supports only +/-1 minor of client skew, so the session pins talosctl
# and kubectl PER UPGRADE STEP to the step's target (`use-versions`, or the
# UPGRADE_TALOS_MINOR / UPGRADE_K8S_MINOR env applied by the entrypoint).
# Every minor in the upgrade window is installed under /opt/<tool>/<minor>/;
# exact patch pins, never a floating "latest" lookup. The window is Talos 1.12-1.14 (the
# cluster runs 1.12 - see LAST_MEASURED_CLUSTER_TALOS in
# scripts/version_audit.py) and Kubernetes 1.34-1.37.
# omnictl must track the running Omni server; kept identical to infra-shell /
# kali (scripts/tests/test_upgrade_session_image.py).
ARG TALOSCTL_1_12_VERSION=v1.12.12
ARG TALOSCTL_1_13_VERSION=v1.13.12
ARG TALOSCTL_1_14_VERSION=v1.14.5
ARG KUBECTL_1_34_VERSION=v1.34.13
ARG KUBECTL_1_35_VERSION=v1.35.10
ARG KUBECTL_1_36_VERSION=v1.36.6
ARG KUBECTL_1_37_VERSION=v1.37.2
ARG OMNICTL_VERSION=v0.45.1

# talosctl: checksums come from each release's own sha256sum.txt.
RUN set -eux; \
    for pair in \
      "1.12 ${TALOSCTL_1_12_VERSION}" \
      "1.13 ${TALOSCTL_1_13_VERSION}" \
      "1.14 ${TALOSCTL_1_14_VERSION}"; do \
      set -- $pair; minor="$1"; ver="$2"; \
      asset="talosctl-linux-${TARGETARCH}"; \
      base="https://github.com/siderolabs/talos/releases/download/${ver}"; \
      mkdir -p "/opt/talosctl/${minor}"; \
      curl -fsSL -o "/tmp/${asset}" "${base}/${asset}"; \
      curl -fsSL -o /tmp/talos-sha256sum.txt "${base}/sha256sum.txt"; \
      (cd /tmp && grep " ${asset}\$" talos-sha256sum.txt | sha256sum --check -); \
      install -m 0755 "/tmp/${asset}" "/opt/talosctl/${minor}/talosctl"; \
      rm -f "/tmp/${asset}" /tmp/talos-sha256sum.txt; \
    done

# kubectl: dl.k8s.io publishes <binary>.sha256 beside every binary.
RUN set -eux; \
    for pair in \
      "1.34 ${KUBECTL_1_34_VERSION}" \
      "1.35 ${KUBECTL_1_35_VERSION}" \
      "1.36 ${KUBECTL_1_36_VERSION}" \
      "1.37 ${KUBECTL_1_37_VERSION}"; do \
      set -- $pair; minor="$1"; ver="$2"; \
      base="https://dl.k8s.io/release/${ver}/bin/linux/${TARGETARCH}"; \
      mkdir -p "/opt/kubectl/${minor}"; \
      curl -fsSL -o /tmp/kubectl "${base}/kubectl"; \
      echo "$(curl -fsSL "${base}/kubectl.sha256")  /tmp/kubectl" | sha256sum --check -; \
      install -m 0755 /tmp/kubectl "/opt/kubectl/${minor}/kubectl"; \
      rm -f /tmp/kubectl; \
    done

RUN set -eux; \
    asset="omnictl-linux-${TARGETARCH}"; \
    base="https://github.com/siderolabs/omni/releases/download/${OMNICTL_VERSION}"; \
    curl -fsSL -o "/tmp/${asset}" "${base}/${asset}"; \
    curl -fsSL -o /tmp/omni-sha256sum.txt "${base}/sha256sum.txt"; \
    (cd /tmp && grep " ${asset}\$" omni-sha256sum.txt | sha256sum --check -); \
    install -m 0755 "/tmp/${asset}" /usr/local/bin/omnictl; \
    rm -f "/tmp/${asset}" /tmp/omni-sha256sum.txt

# -- Agent CLIs ---------------------------------------------------------------
# claude comes from agent-base (npm global, /usr/lib/node_modules) - never
# the claude self-installer subcommand, whose download buffers ~17x in anon memory. codex is
# installed the same way multi-agent-shell does, same pin.
ARG CODEX_VERSION=0.145.0
RUN npm install -g --omit=dev @openai/codex@${CODEX_VERSION} \
 && npm cache clean --force

# The CLIs must not try to self-update into a read-only/ephemeral home (the
# in-pod auto-updater OOMs the pod: see frank-gotchas). Updates ship by
# rebuilding this image. Writes land in the emptyDir HOME or /tmp only.
ENV DISABLE_AUTOUPDATER=1 \
    npm_config_cache=/tmp/.npm \
    XDG_CACHE_HOME=/tmp/.cache

COPY --chown=root:root rootfs/ /
RUN chmod 0755 /usr/local/bin/use-versions /usr/local/bin/upgrade-session-entrypoint

USER claude
WORKDIR /home/claude
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/upgrade-session-entrypoint"]
CMD ["bash"]
