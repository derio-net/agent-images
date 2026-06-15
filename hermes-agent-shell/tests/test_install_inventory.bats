#!/usr/bin/env bats
# Tests the three new inventory keys added by the multi-harness standard:
# harnesses, mcp-servers, skills. The existing keys (mise/npm-global/pipx/cargo)
# are exercised by the CI smoke job, not here.

setup() {
  export TMP_HOME=$(mktemp -d)
  export HOME=$TMP_HOME
  mkdir -p "$HOME/.claude"
  # Redirect lib.sh state/log dirs into the tmp HOME so the installer can run
  # as a normal user without /var/* permissions.
  export HERMES_AGENT_SHELL_LOG_DIR="$HOME/log"
  export HERMES_AGENT_SHELL_STATE_DIR="$HOME/state"
  INSTALLER="$(realpath rootfs/usr/local/lib/hermes-agent-shell/install-inventory.sh)"
}

teardown() { rm -rf "$TMP_HOME"; }

# Put no-op stubs for the other section managers on PATH so a focused
# npm-global test doesn't accrue spurious failures from `assert_manager`.
stub_managers() {
  mkdir -p "$HOME/.local/bin"
  for m in mise pipx; do
    printf '#!/bin/sh\nexit 0\n' > "$HOME/.local/bin/$m"
    chmod +x "$HOME/.local/bin/$m"
  done
}

@test "npm-global: a present package declared with a dist-tag is skipped, not reinstalled" {
  # Regression for frank ruflo-shell ENOTEMPTY deadlock: the guard used to
  # pass the full `pkg@tag` spec to `npm ls -g`, which never matches a
  # dist-tag locally, so an already-installed `claude-flow@alpha` was
  # reinstalled on every boot (and eventually deadlocked on a stale npm
  # retired dir). The presence check must be by package NAME.
  stub_managers
  # Stub npm: claude-flow IS installed, but `npm ls -g claude-flow@alpha`
  # (the tagged spec) does not resolve — exactly real npm behaviour.
  export NPM_LOG="$HOME/npm-install.log"
  cat > "$HOME/.local/bin/npm" <<STUB
#!/bin/sh
case "\$1" in
  ls)
    case "\$3" in
      claude-flow)   exit 0 ;;   # present, queried by name
      claude-flow@*) exit 1 ;;   # tagged spec never matches (the bug trigger)
      *)             exit 1 ;;
    esac ;;
  install) echo "install \$*" >> "$NPM_LOG"; exit 0 ;;
esac
exit 1
STUB
  chmod +x "$HOME/.local/bin/npm"
  cat > "$HOME/inventory.yaml" <<'YAML'
npm-global:
  - "claude-flow@alpha"
YAML
  run env PATH="$HOME/.local/bin:$PATH" INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$status" -eq 0 ]
  # Must be reported as already-present and NOT reinstalled.
  [[ "$output" == *"= npm claude-flow@alpha"* ]]
  [ ! -f "$NPM_LOG" ]
  echo "$output" | grep -qE 'failed=0'
}

# Seed a local bare git repo with one commit on `main` and echo its path.
# Used as a network-free skill source.
seed_bare_repo() {
  local remote seed
  remote=$(mktemp -d)
  git init -q --bare "$remote/superpowers.git"
  seed=$(mktemp -d)
  git -C "$seed" init -q
  git -C "$seed" config user.email t@t
  git -C "$seed" config user.name t
  : > "$seed/README"
  git -C "$seed" add README
  git -C "$seed" -c commit.gpgsign=false commit -qm seed
  git -C "$seed" branch -M main
  git -C "$seed" push -q "$remote/superpowers.git" main
  echo "$remote/superpowers.git"
}

@test "harnesses: latest invokes update command" {
  cat > "$HOME/inventory.yaml" <<'YAML'
harnesses:
  claude: latest
YAML
  # Stub `claude` to record invocation. The installer is expected to call
  # `claude update` (or whatever the harness manifest declares); presence in
  # the log file is sufficient to prove the key was handled.
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/claude" <<STUB
#!/bin/sh
echo "claude \$*" >> "$HOME/claude.log"
STUB
  chmod +x "$HOME/.local/bin/claude"
  PATH="$HOME/.local/bin:$PATH" INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  grep -q 'claude update' "$HOME/claude.log"
}

@test "mcp-servers: appends to per-harness mcp.json idempotently" {
  cat > "$HOME/inventory.yaml" <<'YAML'
mcp-servers:
  claude:
    - name: context7
      command: npx
      args: ["-y", "@upstash/context7-mcp"]
YAML
  INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"   # idempotency
  # Two runs must produce exactly one entry under .mcpServers.
  [ "$(jq '.mcpServers | length' "$HOME/.claude/mcp.json")" = "1" ]
  [ "$(jq -r '.mcpServers.context7.command' "$HOME/.claude/mcp.json")" = "npx" ]
}

@test "skills: clones git source into per-harness skills dir" {
  # Use a local bare repo as the source so we don't touch network.
  tmp_remote=$(mktemp -d)
  git init -q --bare "$tmp_remote/superpowers.git"
  # Seed the bare repo with a single commit so `git clone` does not yield
  # an empty working tree (which still creates the dir, but we also want
  # to prove the clone succeeded end-to-end).
  tmp_seed=$(mktemp -d)
  git -C "$tmp_seed" init -q
  git -C "$tmp_seed" config user.email t@t
  git -C "$tmp_seed" config user.name t
  : > "$tmp_seed/README"
  git -C "$tmp_seed" add README
  git -C "$tmp_seed" -c commit.gpgsign=false commit -qm seed
  git -C "$tmp_seed" branch -M main
  git -C "$tmp_seed" push -q "$tmp_remote/superpowers.git" main
  cat > "$HOME/inventory.yaml" <<YAML
skills:
  claude:
    - name: superpowers
      source: git+file://$tmp_remote/superpowers.git
      ref: main
YAML
  INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ -d "$HOME/.claude/skills/superpowers/.git" ]
}

@test "fail-open: broken harness pin logs but exits 0" {
  cat > "$HOME/inventory.yaml" <<'YAML'
harnesses:
  nonexistent_xyz_no_such_harness: latest
YAML
  run env INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$status" -eq 0 ]
  [[ "$output" == *"nonexistent_xyz_no_such_harness"* ]]
}

@test "empty inventory: clean exit, no errors" {
  echo '{}' > "$HOME/inventory.yaml"
  run env INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$status" -eq 0 ]
}

@test "skills: successful clone is counted in the summary (no subshell loss)" {
  bare="$(seed_bare_repo)"
  cat > "$HOME/inventory.yaml" <<YAML
skills:
  claude:
    - name: superpowers
      source: git+file://$bare
      ref: main
YAML
  run env INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$status" -eq 0 ]
  # The clone must register in installed=N (regression guard: the counter
  # used to be lost to a pipe-induced subshell and reported installed=0).
  [[ "$output" == *"✓ skill claude/superpowers cloned"* ]]
  echo "$output" | grep -qE 'installed=[1-9]'
}

@test "skills: second run is idempotent (fast-forwards, not re-clone)" {
  bare="$(seed_bare_repo)"
  cat > "$HOME/inventory.yaml" <<YAML
skills:
  claude:
    - name: superpowers
      source: git+file://$bare
      ref: main
YAML
  INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  run env INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$status" -eq 0 ]
  [[ "$output" == *"= skill claude/superpowers checked out"* ]]
  [ -d "$HOME/.claude/skills/superpowers/.git" ]
}

@test "skills: broken source is accounted as failed (not silent)" {
  cat > "$HOME/inventory.yaml" <<'YAML'
skills:
  claude:
    - name: bogus
      source: git+file:///nonexistent/no/such/repo.git
      ref: main
YAML
  run env INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  # Fail-open: still exits 0, but the failure must show in the summary so the
  # Telegram notifier fires (unlike the previous warn-only behaviour).
  [ "$status" -eq 0 ]
  echo "$output" | grep -qE 'failed=[1-9]'
}

@test "removed.skills: deletes the cloned skill dir" {
  bare="$(seed_bare_repo)"
  cat > "$HOME/inventory.yaml" <<YAML
skills:
  claude:
    - name: superpowers
      source: git+file://$bare
      ref: main
YAML
  INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ -d "$HOME/.claude/skills/superpowers" ]
  cat > "$HOME/inventory.yaml" <<'YAML'
removed:
  skills:
    claude:
      - superpowers
YAML
  run env INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$status" -eq 0 ]
  [ ! -d "$HOME/.claude/skills/superpowers" ]
}

@test "removed.mcp-servers: deletes the named server from mcp.json" {
  cat > "$HOME/inventory.yaml" <<'YAML'
mcp-servers:
  claude:
    - name: context7
      command: npx
      args: ["-y", "@upstash/context7-mcp"]
YAML
  INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$(jq '.mcpServers | length' "$HOME/.claude/mcp.json")" = "1" ]
  cat > "$HOME/inventory.yaml" <<'YAML'
removed:
  mcp-servers:
    claude:
      - context7
YAML
  run env INVENTORY="$HOME/inventory.yaml" bash "$INSTALLER"
  [ "$status" -eq 0 ]
  [ "$(jq '.mcpServers | length' "$HOME/.claude/mcp.json")" = "0" ]
}
