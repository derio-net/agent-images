ARG AGENT_BASE_SHA=latest
FROM ghcr.io/derio-net/agent-base:${AGENT_BASE_SHA}

ARG TARGETARCH
ARG TALOSCTL_VERSION=v1.9.5
ARG OMNICTL_VERSION=v0.45.1

USER root

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

# ── sshd + Kali tooling + logrotate (for rotate-logs.sh) + tmux/mosh (persistent shells) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server kali-tools-top10 nmap netcat-traditional logrotate \
      tmux mosh locales-all \
    && mkdir -p /run/sshd /var/run/sshd \
    && rm -rf /var/lib/apt/lists/*

# mosh requires a UTF-8 locale on both client and server
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

# ── kubectl, talosctl, omnictl (duplicated with vk-local — promote on third consumer) ──
RUN curl -fsSL -o /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${TARGETARCH}/kubectl" \
    && chmod +x /usr/local/bin/kubectl
RUN curl -fsSL -o /usr/local/bin/talosctl \
      "https://github.com/siderolabs/talos/releases/download/${TALOSCTL_VERSION}/talosctl-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/talosctl
RUN curl -fsSL -o /usr/local/bin/omnictl \
      "https://github.com/siderolabs/omni/releases/download/${OMNICTL_VERSION}/omnictl-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/omnictl

# ── Config lives in /opt/ (PVC hides /home/claude) ──
COPY assets/sshd_config /opt/sshd_config

# ── Agent scripts (immutable, always from image) ──
COPY scripts/ /opt/scripts/
RUN chmod +x /opt/scripts/*.sh 2>/dev/null || true \
    && chmod +x /opt/scripts/*.py 2>/dev/null || true

# ── Config templates (seeded to PVC on first boot — user-modifiable) ──
COPY config-templates/crontab.txt /opt/crontab
COPY config-templates/bashrc /opt/bashrc
COPY config-templates/settings.json /opt/settings.json
COPY config-templates/gitconfig /opt/gitconfig

# ── Cron env loader ──
RUN printf '#!/bin/bash\nexport $(xargs -0 < /proc/1/environ)\n' > /opt/load-env.sh \
    && chmod +x /opt/load-env.sh

# ── Entrypoint ──
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER claude
WORKDIR /home/claude
EXPOSE 2222
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
