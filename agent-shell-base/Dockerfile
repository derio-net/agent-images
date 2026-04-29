ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-base:${BASE_SHA}

ARG AGENT_USER=agent
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG AGENT_HOME=/home/agent
ENV AGENT_USER=${AGENT_USER} AGENT_UID=${AGENT_UID} AGENT_HOME=${AGENT_HOME}

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server \
      tmux mosh locales-all \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /var/run/sshd

RUN mkdir -p /usr/local/share/tmux-plugins \
    && git clone --depth 1 https://github.com/tmux-plugins/tmux-resurrect /usr/local/share/tmux-plugins/tmux-resurrect \
    && git clone --depth 1 https://github.com/tmux-plugins/tmux-continuum /usr/local/share/tmux-plugins/tmux-continuum

ARG S6_OVERLAY_VERSION=3.2.0.2
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp/
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz \
    && rm /tmp/s6-overlay-*.tar.xz

ENV S6_KEEP_ENV=1 \
    S6_VERBOSITY=2 \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_KILL_GRACETIME=10000

RUN groupadd --gid ${AGENT_GID} ${AGENT_USER} \
    && useradd --uid ${AGENT_UID} --gid ${AGENT_GID} \
               --create-home --home-dir ${AGENT_HOME} \
               --shell /bin/bash ${AGENT_USER}

COPY etc/ /etc/
RUN chmod +x /etc/cont-init.d/* /etc/services.d/*/run /etc/services.d/*/finish /etc/cont-finish.d/*

COPY sshd_config /opt/sshd_config
RUN sed -i "s|__AGENT_HOME__|${AGENT_HOME}|g" /opt/sshd_config

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}

ENTRYPOINT ["/init"]
