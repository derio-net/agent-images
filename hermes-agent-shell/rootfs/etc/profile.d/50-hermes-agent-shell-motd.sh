#!/bin/sh
# hermes-agent-shell auth-status MOTD — printed on SSH login.
#
# hermes is the documented exception to the multi-harness standard's
# "no API tokens" contract (see docs/standards/multi-harness-shells.md
# § "Auth model — subscription, not API tokens"): it has no
# subscription/OAuth flow today, so its inference auth is OPENAI_BASE_URL
# + OPENAI_API_KEY set by the Frank manifest and sourced via ESO from
# Infisical. The standard's auth-status MOTD shows hermes as
# `(BYOK — no login flow)` rather than ✓ or ✗.
#
# We only surface a hint when OPENAI_BASE_URL is unset — the env vars
# themselves are Frank/ESO's responsibility, not the image's.

echo "Harness auth status:"
echo "  ~ hermes     (BYOK — no login flow)"
if [ -z "$OPENAI_BASE_URL" ]; then
  echo "    note: OPENAI_BASE_URL not set; hermes won't reach LiteLLM"
fi
