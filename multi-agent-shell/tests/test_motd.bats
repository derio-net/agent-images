#!/usr/bin/env bats
# Tests the auth-status MOTD drop-in for multi-agent-shell.
# The detector reads only the credential file paths declared
# in the harness manifest; presence-only, no validity check.

setup() {
  export TMP_HOME="$(mktemp -d)"
  export HOME="$TMP_HOME"
  MOTD="$(realpath rootfs/etc/profile.d/50-multi-agent-shell-motd.sh)"
}

teardown() { rm -rf "$TMP_HOME"; }

@test "no creds: all harnesses show ✗ not logged in" {
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✗ claude"* ]]
  [[ "$output" == *"✗ codex"* ]]
  [[ "$output" == *"✗ agy"* ]]
  [[ "$output" == *"✗ opencode"* ]]
}

@test "agy hint is the bare command, not 'agy login'" {
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"run: agy"* ]]
  [[ "$output" != *"run: agy login"* ]]
}

@test "codex hint is the headless device flow, not the browser login server" {
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  # plain 'codex login' spins a localhost login server useless on a headless pod.
  [[ "$output" == *"run: codex login --device-auth"* ]]
}

@test "claude creds present: shows ✓ for claude only" {
  mkdir -p "$TMP_HOME/.claude"
  echo '{}' > "$TMP_HOME/.claude/credentials.json"
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✓ claude"* ]]
  [[ "$output" == *"✗ codex"* ]]
}

@test "codex creds present at ~/.codex/auth.json: shows ✓ for codex" {
  # Regression guard: codex writes CODEX_HOME (~/.codex), not ~/.config/codex.
  # The old path made an authenticated codex read as "not logged in".
  mkdir -p "$TMP_HOME/.codex"
  echo '{}' > "$TMP_HOME/.codex/auth.json"
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✓ codex"* ]]
}

@test "agy creds present: shows ✓ for agy" {
  mkdir -p "$TMP_HOME/.gemini/antigravity-cli"
  echo 'token' > "$TMP_HOME/.gemini/antigravity-cli/antigravity-oauth-token"
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✓ agy"* ]]
  [[ "$output" == *"✗ codex"* ]]
}
