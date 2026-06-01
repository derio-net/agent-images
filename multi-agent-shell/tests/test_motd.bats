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
  [[ "$output" == *"✗ gemini"* ]]
  [[ "$output" == *"✗ opencode"* ]]
}

@test "claude creds present: shows ✓ for claude only" {
  mkdir -p "$TMP_HOME/.claude"
  echo '{}' > "$TMP_HOME/.claude/credentials.json"
  run bash "$MOTD"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✓ claude"* ]]
  [[ "$output" == *"✗ codex"* ]]
}
