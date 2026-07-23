ARG BASE_SHA=latest
FROM ghcr.io/derio-net/agent-shell-base:${BASE_SHA}

# Preserve existing PV state: kali identity stays as `claude` / `/home/claude`.
ARG AGENT_USER=claude
ARG AGENT_HOME=/home/claude
ENV AGENT_USER=${AGENT_USER} AGENT_HOME=${AGENT_HOME} HOME=${AGENT_HOME}

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
# Mirror: pin the official Cloudflare-backed CDN (kali.download), NOT the
# http.kali.org redirector. http.kali.org round-robins to community mirrors
# whose pool/ can lag their Packages index during fast rolling transitions
# (e.g. the GCC-16 churn of 2026-05): the index advertises gcc-16-base
# 16-20260322-1 but the .deb 404s, failing dist-upgrade. kali.download keeps
# index↔pool consistent. See docs/runbooks/frank-gotchas (kali mirror skew).
#
# Dpkg::Options --force-overwrite: the bookworm→kali-rolling jump crosses the
# Debian 64-bit time_t (t64) transition, where renamed/merged library packages
# legitimately ship the same SONAME file as the bookworm package they replace
# (e.g. kali libcurl4-gnutls 8.20.0-5 ships
# /usr/lib/x86_64-linux-gnu/libcurl-gnutls.so.4.8.0, still owned by bookworm
# libcurl3-gnutls 7.88.1-10+deb12u14). dpkg refuses the cross-package overwrite
# and aborts dist-upgrade; --force-overwrite is the canonical resolution — it
# only permits file overwrites, never dependency breakage.
#
# REAL cause of the 2026-07 dist-upgrade failure (misdiagnosed as config-ordering
# in #138 — that convergence hardening did NOT fix it): the base lineage
# (base/Dockerfile, agent-shell-base/Dockerfile) sets a PATH WITHOUT /usr/sbin or
# /sbin. The t64 library renames make dpkg run the maintainer scripts of
# tpm-udev / libtss2* / systemd, which invoke `ldconfig` and `start-stop-daemon`
# (both in /usr/sbin). dpkg can't find them ("dpkg: error: 2 expected programs
# not found in PATH", "Package tpm-udev is not configured yet"), so every
# configure fails and dist-upgrade cascades to exit 100. No amount of
# --force-overwrite or `dpkg --configure -a` fixes a missing PATH. Prepend the
# sbin dirs for this RUN so the maintainer scripts resolve. (The proper root fix
# is to add sbin to the base images' ENV PATH — larger blast radius since it
# changes every descendant's runtime PATH, so it's a separate follow-up.)
#
# AND /run ownership (2026-07): agent-shell-base chowns /run to the agent uid
# (1000) so s6-overlay can write its supervisor sockets there at runtime. But
# systemd 261's tmpfiles refuses an "unsafe path transition" when creating
# root-owned /run/systemd under a non-root /run, so `systemd` fails to configure
# during dist-upgrade — and tpm-udev (depends on systemd) → libtss2* (depend on
# tpm-udev) cascade to exit 100. Reset /run to root just for the upgrade so
# systemd configures, then restore agent ownership (1000:1000) for the s6 runtime.
RUN export PATH="/usr/local/sbin:/usr/sbin:/sbin:$PATH" \
    && apt-get update && apt-get install -y --no-install-recommends \
      lsb-release wget gnupg \
    && wget -qO - https://archive.kali.org/archive-key.asc \
      | gpg --dearmor -o /usr/share/keyrings/kali-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/kali-archive-keyring.gpg] https://kali.download/kali kali-rolling main non-free contrib" \
      > /etc/apt/sources.list.d/kali.list \
    && apt-get update \
    && chown root:root /run \
    && apt-get dist-upgrade -y -o Dpkg::Options::="--force-overwrite" \
    && chown -R 1000:1000 /run \
    && rm -rf /var/lib/apt/lists/*

# ── Kali tooling + logrotate (openssh-server/tmux/mosh inherited from agent-shell-base) ──
RUN apt-get update && apt-get install -y --no-install-recommends \
      kali-tools-top10 nmap netcat-traditional logrotate \
    && rm -rf /var/lib/apt/lists/*

# ── fr bridge — PVC-resident install, not image-baked ──
# fr lives in $HOME/.local/share/uv/tools/fr/ on the shared agent-home PVC,
# installed by etc/cont-init.d/55-install-fr-bridge on first boot via
# `uv tool install`. This makes bridge bumps a one-liner inside the running
# pod (`uv tool install --force --from 'fr @ git+...@<tag>#subdirectory=packages/fr'
# --with 'fr-vk @ git+...@<tag>#subdirectory=packages/fr-vk' fr`) rather
# than a Dockerfile change + image rebuild + redeploy. The default pin is
# tracked in the init script's FR_BRIDGE_PIN below.
#
# Pre-2026-05-18 layout (now retired): the bridge lived at /opt/vk-bridge-venv
# in the image, wrapper at /opt/vk-bridge/run.sh. See PR #85 history if you
# need the rationale for the move.

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
# Loads every env var written to the s6-overlay envdir. Each file under
# /run/s6/basedir/env/ has name = env var, content = value (no trailing newline).
# Replaces the legacy `/proc/1/environ` reader: under s6-overlay, PID 1 is
# s6-svscan, which deliberately does not propagate the K8s envFrom-injected
# variables that tini used to carry. The envdir is the documented, stable source.
# Uses `printf -v` rather than `eval` because env values can contain shell
# metacharacters (=, ", $, newlines).
COPY config-templates/load-env.sh /opt/load-env.sh
RUN chmod +x /opt/load-env.sh

# ── Kali-specific cont-init.d: seed config templates on first boot ──
COPY etc/cont-init.d/ /etc/cont-init.d/
RUN chmod +x /etc/cont-init.d/*

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
