ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}

# Preserve existing PV state: kali identity stays as `claude` / `/home/claude`.
ARG AGENT_USER=claude
ARG AGENT_HOME=/home/claude
ENV AGENT_USER=${AGENT_USER} AGENT_HOME=${AGENT_HOME} HOME=${AGENT_HOME}

ARG TARGETARCH
ARG TALOSCTL_VERSION=v1.9.5
ARG OMNICTL_VERSION=v0.45.1

USER root

# agent-shell-base created the default `agent` user at UID 1000.
# Replace with the legacy `claude` identity so PV state is preserved across restarts.
RUN if ! id -u "${AGENT_USER}" >/dev/null 2>&1; then \
        if getent passwd 1000 >/dev/null; then \
            existing=$(getent passwd 1000 | cut -d: -f1); \
            /usr/sbin/userdel -r "${existing}" 2>/dev/null || true; \
        fi; \
        if getent group 1000 >/dev/null; then \
            existing_grp=$(getent group 1000 | cut -d: -f1); \
            /usr/sbin/groupdel "${existing_grp}" 2>/dev/null || true; \
        fi; \
        /usr/sbin/groupadd --gid 1000 ${AGENT_USER}; \
        /usr/sbin/useradd --uid 1000 --gid 1000 \
                --create-home --home-dir ${AGENT_HOME} \
                --shell /bin/bash ${AGENT_USER}; \
    fi

# Re-substitute sshd_config: agent-shell-base baked in `/home/agent`; replace with
# the kali-specific AGENT_HOME at kali build time. The grep assertion confirms the
# substitution actually fired — catches any future change to agent-shell-base's default path.
RUN sed -i "s|/home/agent|${AGENT_HOME}|g" /opt/sshd_config \
    && grep -q "${AGENT_HOME}" /opt/sshd_config

# ── Kali archive + dist-upgrade (resolve bookworm→kali-rolling version conflicts) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
      lsb-release wget gnupg \
    && wget -qO - https://archive.kali.org/archive-key.asc \
      | gpg --dearmor -o /usr/share/keyrings/kali-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/kali-archive-keyring.gpg] https://http.kali.org/kali kali-rolling main non-free contrib" \
      > /etc/apt/sources.list.d/kali.list \
    && apt-get update \
    && apt-get dist-upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# ── Kali tooling + logrotate (openssh-server/tmux/mosh inherited from agent-shell-base) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
      kali-tools-top10 nmap netcat-traditional logrotate \
    && rm -rf /var/lib/apt/lists/*

# mosh requires a UTF-8 locale on both client and server
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

# ── kubectl, talosctl, omnictl ──
RUN curl -fsSL -o /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${TARGETARCH}/kubectl" \
    && chmod +x /usr/local/bin/kubectl
RUN curl -fsSL -o /usr/local/bin/talosctl \
      "https://github.com/siderolabs/talos/releases/download/${TALOSCTL_VERSION}/talosctl-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/talosctl
RUN curl -fsSL -o /usr/local/bin/omnictl \
      "https://github.com/siderolabs/omni/releases/download/${OMNICTL_VERSION}/omnictl-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/omnictl

# ── Agent scripts (immutable, always from image) ──
COPY scripts/ /opt/scripts/
RUN chmod +x /opt/scripts/*.sh 2>/dev/null || true \
    && chmod +x /opt/scripts/*.py 2>/dev/null || true

# ── Config templates (seeded to PVC on first boot via 50-seed-config) ──
COPY config-templates/crontab.txt /opt/crontab
COPY config-templates/bashrc /opt/bashrc
COPY config-templates/settings.json /opt/settings.json
COPY config-templates/gitconfig /opt/gitconfig

# ── Cron env loader ──
RUN printf '#!/bin/bash\nexport $(xargs -0 < /proc/1/environ)\n' > /opt/load-env.sh \
    && chmod +x /opt/load-env.sh

# ── Kali-specific cont-init.d: seed config templates on first boot ──
COPY etc/cont-init.d/ /etc/cont-init.d/
RUN chmod +x /etc/cont-init.d/*

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
