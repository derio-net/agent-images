#!/usr/bin/env bats

setup() {
  HOOK="$(realpath hermes-agent-shell/rootfs/etc/cont-init.d/36-hermes-strict-state-perms)"
  STATE_ROOT="$BATS_TEST_TMPDIR/state"
  export STATE_ROOT
}

run_hook() { run bash "$HOOK"; }

@test "no env configured is a clean no-op" {
  unset HERMES_AGENT_SHELL_STRICT_PATHS
  run_hook
  [ "$status" -eq 0 ]
}

@test "missing path is skipped fail-open" {
  export HERMES_AGENT_SHELL_STRICT_PATHS="$STATE_ROOT/missing:700:600"
  run_hook
  [ "$status" -eq 0 ]
  [[ "$output" == *"skip missing path"* ]]
}

@test "enforces default strict modes recursively" {
  mkdir -p "$STATE_ROOT/pg/base"
  printf '16\n' > "$STATE_ROOT/pg/PG_VERSION"
  printf 'config\n' > "$STATE_ROOT/pg/postgresql.conf"
  chmod 2775 "$STATE_ROOT/pg" "$STATE_ROOT/pg/base"
  chmod 664 "$STATE_ROOT/pg/PG_VERSION" "$STATE_ROOT/pg/postgresql.conf"

  export HERMES_AGENT_SHELL_STRICT_PATHS="$STATE_ROOT/pg"
  run_hook
  [ "$status" -eq 0 ]
  [ "$(stat -c '%a' "$STATE_ROOT/pg")" = "700" ]
  [ "$(stat -c '%a' "$STATE_ROOT/pg/base")" = "700" ]
  [ "$(stat -c '%a' "$STATE_ROOT/pg/PG_VERSION")" = "600" ]
  [ "$(stat -c '%a' "$STATE_ROOT/pg/postgresql.conf")" = "600" ]
}

@test "supports custom dir and file modes" {
  mkdir -p "$STATE_ROOT/custom/sub"
  printf 'x\n' > "$STATE_ROOT/custom/file.txt"
  chmod 775 "$STATE_ROOT/custom" "$STATE_ROOT/custom/sub"
  chmod 664 "$STATE_ROOT/custom/file.txt"

  export HERMES_AGENT_SHELL_STRICT_PATHS="$STATE_ROOT/custom:750:640"
  run_hook
  [ "$status" -eq 0 ]
  [ "$(stat -c '%a' "$STATE_ROOT/custom")" = "750" ]
  [ "$(stat -c '%a' "$STATE_ROOT/custom/sub")" = "750" ]
  [ "$(stat -c '%a' "$STATE_ROOT/custom/file.txt")" = "640" ]
}
