#!/usr/bin/env bats
# Tests the first-boot venv seed hook (cont-init.d/35-hermes-venv-seed).
#
# The image ships a RELOCATABLE seed venv at $SEED; on first boot the hook
# copies it onto the writable /home/agent PVC at $LIVE so uid 1000 can patch
# Hermes in place and the changes persist across restarts. The hook is
# version-aware: an image/Hermes bump (new $SEED/.seed-version) re-seeds,
# while an unchanged version is a no-op that PRESERVES in-pod hot-patches.
#
# The hook reads SEED/LIVE from the environment (defaulting to the real image
# paths) precisely so this test can point them at tmpdirs and run with plain
# `bash` — no container, no s6, no network.

setup() {
  HOOK="$(realpath rootfs/etc/cont-init.d/35-hermes-venv-seed)"
  SEED="$BATS_TEST_TMPDIR/seed"
  LIVE="$BATS_TEST_TMPDIR/live"
  export SEED LIVE
  # Fake "venv": a marker + a representative file.
  mkdir -p "$SEED/bin"
  printf 'hermes\n' > "$SEED/bin/hermes"
  printf '0.15.2+autocontinue1\n' > "$SEED/.seed-version"
}

run_hook() { run bash "$HOOK"; }

@test "first boot seeds the venv onto the PVC path" {
  [ ! -e "$LIVE" ]
  run_hook
  [ "$status" -eq 0 ]
  [ -f "$LIVE/bin/hermes" ]
  [ "$(cat "$LIVE/.seed-version")" = "0.15.2+autocontinue1" ]
}

@test "same-version re-run is a no-op and preserves an in-pod patch" {
  run_hook
  [ "$status" -eq 0 ]
  # Operator hot-patches the live venv.
  printf 'patched\n' > "$LIVE/bin/hermes"
  printf 'sentinel\n' > "$LIVE/MY_PATCH"
  run_hook
  [ "$status" -eq 0 ]
  [ -f "$LIVE/MY_PATCH" ]                       # patch survived
  [ "$(cat "$LIVE/bin/hermes")" = "patched" ]   # edit survived
}

@test "a seed-version bump re-seeds and supersedes in-pod patches" {
  run_hook
  printf 'sentinel\n' > "$LIVE/MY_PATCH"
  printf 'patched\n' > "$LIVE/bin/hermes"
  # Image bump: new seed version + new content.
  printf '0.16.0+autocontinue1\n' > "$SEED/.seed-version"
  printf 'hermes-new\n' > "$SEED/bin/hermes"
  run_hook
  [ "$status" -eq 0 ]
  [ ! -e "$LIVE/MY_PATCH" ]                          # stale patch removed
  [ "$(cat "$LIVE/.seed-version")" = "0.16.0+autocontinue1" ]
  [ "$(cat "$LIVE/bin/hermes")" = "hermes-new" ]     # fresh seed content
}

@test "missing seed marker is a clean no-op (does not create LIVE)" {
  rm -f "$SEED/.seed-version"
  run_hook
  [ "$status" -eq 0 ]
  [ ! -e "$LIVE" ]
}
