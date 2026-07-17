#!/usr/bin/env bats
# Tests the login-env drop-in that wires PATH + the npm global prefix for the
# operator's interactive shell (rootfs/etc/profile.d/40-multi-agent-shell-paths.sh).

setup() {
  export TMP_HOME="$(mktemp -d)"
  export HOME="$TMP_HOME"
  PATHS="$(realpath rootfs/etc/profile.d/40-multi-agent-shell-paths.sh)"
}

teardown() { rm -rf "$TMP_HOME"; }

@test "npm global prefix points at the PV-resident ~/.local" {
  # A harness self-update (`npm install -g @openai/codex`) must land on the
  # agent-writable home volume, not the root-owned /usr default (EACCES).
  unset NPM_CONFIG_PREFIX
  run bash -c "PATH=/usr/bin:/bin; . '$PATHS'; printf '%s' \"\$NPM_CONFIG_PREFIX\""
  [ "$status" -eq 0 ]
  [ "$output" = "$TMP_HOME/.local" ]
}

@test "an operator's explicit NPM_CONFIG_PREFIX is respected (not clobbered)" {
  run bash -c "PATH=/usr/bin:/bin; export NPM_CONFIG_PREFIX=/custom/prefix; . '$PATHS'; printf '%s' \"\$NPM_CONFIG_PREFIX\""
  [ "$status" -eq 0 ]
  [ "$output" = "/custom/prefix" ]
}

@test "~/.local/bin is PATH-preferred (self-updated build shadows the /usr bootstrap)" {
  run bash -c "PATH=/usr/bin:/bin; . '$PATHS'; printf '%s' \"\$PATH\""
  [ "$status" -eq 0 ]
  # ~/.local/bin must appear before /usr/bin
  [[ "$output" == "$TMP_HOME/.local/bin:"* ]]
}
