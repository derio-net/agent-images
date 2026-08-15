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

# Per docs/standards/multi-harness-shells.md — hermes is the documented
# exception to the standard's "no API tokens" auth contract. It has no
# subscription/OAuth login flow today; instead its inference auth is BYOK
# (OPENAI_BASE_URL + OPENAI_API_KEY) set by the Frank pod manifest and
# sourced via ESO from Infisical. The MOTD reflects this with a
# `(BYOK — no login flow)` row instead of ✓/✗.
#
# Install method: PyPI (`hermes-agent` package, distributed by Nous
# Research at https://github.com/NousResearch/hermes-agent). The
# upstream repo also ships scripts/install.sh — a uv-based clone-and-setup
# bootstrap — but for a container baseline a pinned PyPI install is
# leaner, reproducible, and avoids cloning the whole repo into the image.
# The CLI entry point declared by upstream's pyproject.toml is `hermes`
# (→ hermes_cli.main:main).
#
# Pin is the version corresponding to upstream tag v2026.5.29.2 (commit
# 77a1650c78a4cb1813d8a81fa1da40a15b6a3ec5, dated 2026-05-29). Resolved
# during the implementation of derio-net/agent-images#99 (P2.T1.S1).
# Floats forward via the inventory `harnesses:` key once an operator
# overrides it on first reconcile.
ARG HERMES_VERSION=0.19.0

# Build a RELOCATABLE SEED venv at /opt/hermes-agent (a read-only build
# artifact, NOT the live runtime). `--relocatable` writes console scripts with
# a `#!/bin/sh` polyglot shebang that re-execs the venv python by RELATIVE
# path, so the seed can be copied to another directory and still run. On first
# boot, cont-init.d/35-hermes-venv-seed `cp -a`'s this seed onto the
# /home/agent PVC at /home/agent/.local/opt/hermes-agent — the LIVE venv,
# uid-1000-owned and writable, so the in-pod operator can patch/maintain
# Hermes in place (`hermes update`, site-packages edits) and have it persist
# across pod restarts (frank#496). The venv cannot be baked at the PVC path
# directly: the PVC mount at /home/agent shadows anything baked under it.
#
# The system-python layout from agent-base stays untouched (PEP 668:
# /usr/bin/python3 is externally-managed). uv is provided by agent-base; `uv
# venv` omits pip (uv writes wheels directly), so no ensurepip bootstrap.
#
# NO LOCAL PATCHES as of HERMES_VERSION 0.19.0 — upstream shipped the feature.
#
# History (frank#496): Hermes 0.15.2 hardcoded its "announce-only turn"
# countermeasure (inject `[System: Continue now…]`) to
# `api_mode == "codex_responses"`, so it never fired on the OpenAI-compatible
# LiteLLM path Frank uses (api_mode "chat_completions"). We carried a one-line
# `git apply` patch widening that gate.
#
# In 0.19.0 upstream replaced the hardcoded gate with a real config knob,
# `intent_ack_continuation` (agent/agent_runtime_helpers.py:
# intent_ack_continuation_mode), with four modes mirroring
# `tool_use_enforcement`:
#     "auto" (default) -> codex_only  — the OLD hardcoded behaviour
#     true/always/yes/on -> all       — fires on EVERY api_mode  <-- our patch
#     false/never/no/off -> off
#     [list]             -> all when a substring matches the active model
# So the patch is obsolete: the code it targeted no longer exists (the build
# failed loudly, exactly as the zero-fuzz `git apply` was designed to), and the
# behaviour it forced is now reachable by configuration.
#
# ==> CONSUMERS MUST SET IT: to keep the pre-0.19.0 Frank behaviour, the agent
#     config.yaml needs `agent.intent_ack_continuation: true`. That file is PVC
#     state (manual-op `orch-hermes-config-provider`), NOT something this image
#     can set. Without it Hermes silently reverts to codex-only continuation on
#     the chat_completions path.
#
# .seed-version stamps the seed so the first-boot hook re-seeds on an
# image/Hermes bump (and no-ops — preserving in-pod edits — when unchanged).
# The suffix records the LOCAL PATCH SET; bump it whenever that set changes.
# It is now `+nopatches1` because the set is empty.
RUN uv venv --relocatable --python 3.11 /opt/hermes-agent \
 && uv pip install --python /opt/hermes-agent/bin/python \
      "hermes-agent==${HERMES_VERSION}" \
 && printf '%s+nopatches1\n' "${HERMES_VERSION}" > /opt/hermes-agent/.seed-version \
 && ln -sf /home/agent/.local/opt/hermes-agent/bin/hermes /usr/local/bin/hermes \
 && chown -R ${AGENT_UID}:${AGENT_GID} /opt/hermes-agent \
 && /opt/hermes-agent/bin/hermes --version

COPY --chown=root:root rootfs/ /

# Pre-create the dirs the inventory installer writes to. Under K8s
# (runAsUser: 1000, cap-drop=ALL, allowPrivilegeEscalation: false) the agent
# UID cannot create root-owned directories at runtime, and agent-shell-base
# only chowns /run + /var/run. Without these, install-inventory.sh's tee +
# motd write fail silently inside cont-init.d, the installer appears to
# "succeed" (fail-open exit 0), and the operator gets no log and no MOTD.
RUN install -d -o ${AGENT_UID} -g ${AGENT_GID} -m 0755 \
      /var/log/cont-init.d \
      /var/lib/hermes-agent-shell \
 && chmod +x \
      /etc/cont-init.d/35-hermes-venv-seed \
      /etc/cont-init.d/36-hermes-strict-state-perms \
      /etc/cont-init.d/40-shell-inventory \
      /etc/profile.d/40-hermes-agent-shell-paths.sh \
      /etc/profile.d/45-hermes-agent-shell-reconcile-motd.sh \
      /etc/profile.d/50-hermes-agent-shell-motd.sh \
      /usr/local/lib/hermes-agent-shell/install-base-runtimes.sh \
      /usr/local/lib/hermes-agent-shell/install-inventory.sh \
      /usr/local/lib/hermes-agent-shell/notify-telegram.sh \
      /usr/local/lib/hermes-agent-shell/lib.sh \
 && /usr/local/lib/hermes-agent-shell/install-base-runtimes.sh \
 && ln -sf /usr/local/lib/hermes-agent-shell/install-inventory.sh \
           /usr/local/bin/hermes-agent-shell-reconcile

USER ${AGENT_USER}
WORKDIR ${AGENT_HOME}
EXPOSE 2222
# ENTRYPOINT inherited from agent-shell-base: /init (s6-overlay)
