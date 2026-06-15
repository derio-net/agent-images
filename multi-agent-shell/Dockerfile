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

# Per docs/standards/multi-harness-shells.md — bake the additional
# subscription/OAuth harness bootstrap shims. claude is inherited from
# agent-base (npm i -g @anthropic-ai/claude-code) and the inherited shim's
# self-update target is $HOME/.local/bin/. The npm-distributed shims
# (codex, opencode) follow the same convention: the operator runs `<h> login`
# once on first SSH; the CLI self-updates or is refreshed via inventory
# reconcile thereafter.
#
# Pins captured during plan execution (npm view <pkg> version on
# 2026-06-01). These pins float forward via the inventory `harnesses:`
# key; the Dockerfile shim is only a bootstrap.
ARG CODEX_VERSION=0.136.0
ARG OPENCODE_VERSION=1.15.13
RUN npm install -g --omit=dev \
      @openai/codex@${CODEX_VERSION} \
      opencode-ai@${OPENCODE_VERSION}

# antigravity CLI (agy) — replaces the gemini CLI (deprecating upstream
# 2026-06-18). Unlike the npm harnesses, agy is binary-distributed via a
# vendor install script, has NO self-update subcommand and NO version-pin
# mechanism, so it is refreshed by IMAGE REBUILD — not the inventory
# `harnesses:` key. Auth is interactive Google OAuth on first run of `agy`
# (no `agy login`, no API key); the credential persists on the PV.
#
# Install via download-then-run (not `curl | bash`) so a curl/TLS failure
# fails the build directly instead of being masked by the pipe — `/bin/sh`
# here has no pipefail. The installer's `--dir` flag drops the binary
# straight onto the global PATH (no relocate needed); a throwaway $HOME
# absorbs the installer's shell-rc edits so they don't bloat root's home,
# and both scratch paths are removed in the same layer. `agy --version`
# gates that the binary installed and is executable (CI smoke re-checks it
# as UID 1000).
RUN mkdir -p /tmp/agy-home \
 && curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy-install.sh \
 && HOME=/tmp/agy-home bash /tmp/agy-install.sh --dir /usr/local/bin </dev/null \
 && rm -rf /tmp/agy-install.sh /tmp/agy-home \
 && agy --version

COPY --chown=root:root rootfs/ /

# Pre-create the dirs the inventory installer writes to. Under K8s
# (runAsUser: 1000, cap-drop=ALL, allowPrivilegeEscalation: false) the agent
# UID cannot create root-owned directories at runtime, and agent-shell-base
# only chowns /run + /var/run. Without these, install-inventory.sh's tee +
# motd write fail silently inside cont-init.d, the installer appears to
# "succeed" (fail-open exit 0), and the operator gets no log and no MOTD.
RUN install -d -o ${AGENT_UID} -g ${AGENT_GID} -m 0755 \
      /var/log/cont-init.d \
      /var/lib/multi-agent-shell \
 && chmod +x \
      /etc/cont-init.d/40-shell-inventory \
      /etc/profile.d/40-multi-agent-shell-paths.sh \
      /etc/profile.d/45-multi-agent-shell-reconcile-motd.sh \
      /etc/profile.d/50-multi-agent-shell-motd.sh \
      /usr/local/lib/multi-agent-shell/install-base-runtimes.sh \
      /usr/local/lib/multi-agent-shell/install-inventory.sh \
      /usr/local/lib/multi-agent-shell/notify-telegram.sh \
      /usr/local/lib/multi-agent-shell/lib.sh \
      /usr/local/lib/multi-agent-shell/agent-session \
 && /usr/local/lib/multi-agent-shell/install-base-runtimes.sh \
 && ln -sf /usr/local/lib/multi-agent-shell/install-inventory.sh \
           /usr/local/bin/multi-agent-shell-reconcile \
 && ln -sf /usr/local/lib/multi-agent-shell/agent-session \
           /usr/local/bin/agent-session

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
