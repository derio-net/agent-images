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
  export MULTI_AGENT_SHELL_LOG_DIR="$HOME/log"
  export MULTI_AGENT_SHELL_STATE_DIR="$HOME/state"
  INSTALLER="$(realpath rootfs/usr/local/lib/multi-agent-shell/install-inventory.sh)"
}

teardown() { rm -rf "$TMP_HOME"; }

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
