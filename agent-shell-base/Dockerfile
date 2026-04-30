ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-base:${BASE_SHA}

ARG AGENT_USER=agent
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG AGENT_HOME=/home/agent
# HOME tracks AGENT_HOME so supervised processes (sshd, supercronic, cont-init scripts)
# do not silently fall back to the parent image's /home/claude.
ENV AGENT_USER=${AGENT_USER} AGENT_UID=${AGENT_UID} AGENT_HOME=${AGENT_HOME} \
    HOME=${AGENT_HOME}

USER root

# supercronic provided by agent-base (v0.2.33) — do not reinstall.
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server \
      tmux mosh locales-all \
      xz-utils \
      passwd \
    && rm -rf /var/lib/apt/lists/*

ARG TMUX_RESURRECT_REF=v4.0.0
ARG TMUX_CONTINUUM_REF=v3.1.0
RUN mkdir -p /usr/local/share/tmux-plugins \
    && git clone --depth 1 --branch ${TMUX_RESURRECT_REF} \
         https://github.com/tmux-plugins/tmux-resurrect /usr/local/share/tmux-plugins/tmux-resurrect \
    && git clone --depth 1 --branch ${TMUX_CONTINUUM_REF} \
         https://github.com/tmux-plugins/tmux-continuum /usr/local/share/tmux-plugins/tmux-continuum

ARG S6_OVERLAY_VERSION=3.2.0.2
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp/
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz \
    && rm /tmp/s6-overlay-*.tar.xz

ENV S6_KEEP_ENV=1 \
    S6_VERBOSITY=2 \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_KILL_GRACETIME=10000 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0

# agent-base ships with the `claude` user at UID/GID 1000. Replace that identity
# with whichever AGENT_USER/AGENT_HOME this image is built for. Idempotent so
# overrides like AGENT_USER=claude (Phase 3 kali) succeed too.
RUN if id -u "${AGENT_USER}" >/dev/null 2>&1; then \
        : "user already present"; \
    else \
        if getent passwd "${AGENT_UID}" >/dev/null; then \
            existing_user=$(getent passwd "${AGENT_UID}" | cut -d: -f1); \
            userdel -r "${existing_user}" 2>/dev/null || true; \
        fi; \
        if getent group "${AGENT_GID}" >/dev/null; then \
            existing_group=$(getent group "${AGENT_GID}" | cut -d: -f1); \
            groupdel "${existing_group}" 2>/dev/null || true; \
        fi; \
        groupadd --gid ${AGENT_GID} ${AGENT_USER}; \
        useradd --uid ${AGENT_UID} --gid ${AGENT_GID} \
                --create-home --home-dir ${AGENT_HOME} \
                --shell /bin/bash ${AGENT_USER}; \
    fi

# s6-overlay v3 needs writable scan-dir and supervisor sockets. Default /run
# is root-owned tmpfs in K8s, so pre-create + chown for the non-root agent.
# Same for sshd's privsep dir.
RUN mkdir -p /run/service /run/s6 /run/s6-rc /var/run/s6 /run/sshd /var/run/sshd \
    && chown -R ${AGENT_UID}:${AGENT_GID} \
         /run/service /run/s6 /run/s6-rc /var/run/s6 /run/sshd /var/run/sshd

COPY etc/ /etc/
RUN chmod +x /etc/cont-init.d/* /etc/services.d/*/run /etc/services.d/*/finish /etc/cont-finish.d/*

COPY sshd_config /opt/sshd_config
RUN sed -i "s|__AGENT_HOME__|${AGENT_HOME}|g" /opt/sshd_config

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}

ENTRYPOINT ["/init"]
