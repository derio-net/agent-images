# hermes-agent-shell-ssh — thin SSH/Mosh sidecar for the two-container
# hermes-agent-shell pod (willikins#285). Built FROM the SAME official Hermes
# tag the main container runs, so the `hermes` CLI invoked over SSH is byte-for-
# byte the gateway's runtime and talks to the shared /opt/data state directly.
#
# It does NOT run the gateway or the dashboard — that is the main container's
# job. This image only adds terminal access (sshd + mosh + tmux) and a login
# identity, then runs sshd in the foreground.
#
# WHY not FROM agent-shell-base like the old single-container image: the whole
# point of the migration is that the main service container is the unmodified
# official image. The sidecar shares its /opt/data layout, HERMES_HOME, PATH and
# CLI — building FROM the same tag guarantees that; agent-shell-base would
# reintroduce a divergent /home/agent world.
ARG HERMES_TAG=v2026.7.20
FROM docker.io/nousresearch/hermes-agent:${HERMES_TAG}

# The official image is Debian trixie and runs as root with HERMES_HOME=/opt/data
# (confirmed from its image config, 2026-07-09). We add a non-root login user
# matching the pod securityContext (runAsUser/Group 1000) whose HOME is the
# shared tool-home PVC at /opt/data/home.
USER root

ARG AGENT_USER=agent
ARG AGENT_UID=1000
ARG AGENT_GID=1000
ARG AGENT_HOME=/opt/data/home

# sshd + mosh + tmux for terminal access, plus the operator-side prerequisites
# the Hermes shell workflows assume: `gh` for GitHub auth / PR work and `rsync`
# for hermes-brain sync + snapshot scripts. C.UTF-8 (glibc built-in) covers
# mosh's UTF-8 requirement, so we skip the ~200MB locales-all the old base
# pulled in.
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server \
      mosh \
      tmux \
      passwd \
      gh \
      rsync \
      curl \
      unzip \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Bun — the JavaScript runtime the client CLI needs (derio-net/frank#759). The
# image ships the RUNTIME ONLY; the CLI itself is installed by the operator at
# runtime, which keeps a private tool's name out of this public repo and puts
# its bytes on the home PVC, where they survive a pod restart.
#
# INSTALLED TO /usr/local/bin, AS ROOT, DELIBERATELY. Bun's own installer
# targets `~/.bun`, and ${AGENT_HOME} here is /opt/data/home — a Longhorn PVC
# MOUNT at runtime. Anything baked under that path is hidden the moment the
# volume mounts, so the obvious install command yields an image that builds
# clean and a container with no `bun` on it. Only the operator's later
# `bun install -g` belongs under $HOME — and there it is wanted, because that
# is precisely what makes it persist.
#
# The architecture is derived, not hardcoded: this image builds amd64 today,
# and a hardcoded x64 asset is how a future multi-arch build ships a silently
# broken image. Verification uses the release's OWN SHASUMS256.txt rather than
# a digest pinned here, so a version bump is a one-line change that cannot
# accidentally skip the check. `bun --version` at the end fails the BUILD if
# the binary does not run, rather than deferring that to a smoke test.
ARG BUN_VERSION=1.3.14
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      amd64) bun_asset=bun-linux-x64 ;; \
      arm64) bun_asset=bun-linux-aarch64 ;; \
      *) echo "unsupported architecture: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    tmp="$(mktemp -d)"; \
    base="https://github.com/oven-sh/bun/releases/download/bun-v${BUN_VERSION}"; \
    curl -fsSL -o "${tmp}/${bun_asset}.zip" "${base}/${bun_asset}.zip"; \
    curl -fsSL -o "${tmp}/SHASUMS256.txt" "${base}/SHASUMS256.txt"; \
    (cd "${tmp}" && sha256sum --check --ignore-missing SHASUMS256.txt); \
    unzip -q "${tmp}/${bun_asset}.zip" -d "${tmp}"; \
    install -m 0755 "${tmp}/${bun_asset}/bun" /usr/local/bin/bun; \
    rm -rf "${tmp}"; \
    bun --version

# Create the login identity. The official image has no UID-1000 user; mirror
# agent-shell-base's idempotent handling in case a future base ships one.
RUN if ! id -u "${AGENT_USER}" >/dev/null 2>&1; then \
        if getent passwd "${AGENT_UID}" >/dev/null; then \
            /usr/sbin/userdel -r "$(getent passwd ${AGENT_UID} | cut -d: -f1)" 2>/dev/null || true; \
        fi; \
        if getent group "${AGENT_GID}" >/dev/null; then \
            /usr/sbin/groupdel "$(getent group ${AGENT_GID} | cut -d: -f1)" 2>/dev/null || true; \
        fi; \
        /usr/sbin/groupadd --gid ${AGENT_GID} ${AGENT_USER}; \
        /usr/sbin/useradd --uid ${AGENT_UID} --gid ${AGENT_GID} \
            --home-dir ${AGENT_HOME} --shell /bin/bash ${AGENT_USER}; \
    fi

# sshd privsep dir owned by the agent UID: a non-root sshd under
# cap-drop=ALL + allowPrivilegeEscalation=false cannot chown /run at runtime
# (same constraint agent-shell-base pre-chowns for). The pod runs everything as
# UID 1000, so login-user == daemon-user and sshd needs no privilege drop.
RUN mkdir -p /run/sshd && chown ${AGENT_UID}:${AGENT_GID} /run/sshd

ENV AGENT_USER=${AGENT_USER} AGENT_UID=${AGENT_UID} AGENT_GID=${AGENT_GID} \
    AGENT_HOME=${AGENT_HOME} HOME=${AGENT_HOME} \
    LANG=C.UTF-8 LC_ALL=C.UTF-8

COPY rootfs/ /
RUN sed -i "s|__AGENT_HOME__|${AGENT_HOME}|g" /opt/sshd_config \
 && chmod 0644 /opt/sshd_config \
 && chmod +x /usr/local/bin/hermes-ssh-sidecar-entrypoint.sh \
 && chmod 0644 /etc/profile.d/36-hermes-bun-path.sh

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# Override the official ENTRYPOINT (/init + main-wrapper.sh, which would start
# the gateway). This sidecar runs sshd only.
ENTRYPOINT ["/usr/local/bin/hermes-ssh-sidecar-entrypoint.sh"]
