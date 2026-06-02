#!/usr/bin/env bats
# Tests the BYOK auth-status MOTD drop-in for hermes-agent-shell.
# Hermes is the documented exception to the multi-harness standard's
# "no API tokens" auth contract — it has no subscription/OAuth login
# flow today, so the MOTD shows `~ hermes (BYOK — no login flow)` rather
# than the ✓/✗ pattern the other harnesses use. We only surface a hint
# when OPENAI_BASE_URL is unset; the env itself is Frank/ESO's concern.

setup() {
  MOTD="$(realpath rootfs/etc/profile.d/50-hermes-agent-shell-motd.sh)"
}

@test "BYOK row prints regardless of env" {
  unset OPENAI_BASE_URL
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Harness auth status:"* ]]
  [[ "$output" == *"~ hermes"* ]]
  [[ "$output" == *"BYOK — no login flow"* ]]
}

@test "OPENAI_BASE_URL unset surfaces the LiteLLM hint" {
  unset OPENAI_BASE_URL
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OPENAI_BASE_URL not set"* ]]
}

@test "OPENAI_BASE_URL set suppresses the hint" {
  OPENAI_BASE_URL=http://litellm.litellm-system:4000/v1 run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"~ hermes"* ]]
  [[ "$output" != *"OPENAI_BASE_URL not set"* ]]
}
