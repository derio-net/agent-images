#!/usr/bin/env bash
# test_seed_config_crontab.sh — harness for etc/cont-init.d/50-seed-config
# crontab re-render logic. Covers three cases:
#   1. First boot: no ~/.crontab → full template is rendered.
#   2. Re-render: ~/.crontab has sentinels → managed block is replaced,
#      user-added lines outside the block are preserved.
#   3. Legacy: ~/.crontab without sentinels → left untouched.
#
# Drives the script via OPT_DIR (pointing at a tmp tree of stub files)
# so it runs portably on macOS dev workstations and Linux CI alike.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$SCRIPT_DIR/etc/cont-init.d/50-seed-config"
TEMPLATE="$SCRIPT_DIR/config-templates/crontab.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Seed stub /opt content the script copies / reads from.
OPT="$TMP/opt"
mkdir -p "$OPT"
cp "$TEMPLATE" "$OPT/crontab"
printf 'stub\n' > "$OPT/load-env.sh"
printf 'stub\n' > "$OPT/bashrc"
printf '{}\n'   > "$OPT/settings.json"
printf '[stub]\n' > "$OPT/gitconfig"

# Wrap the s6 shebang for portable invocation.
SCRIPT_COPY="$TMP/50-seed-config"
{ echo '#!/usr/bin/env bash'; tail -n +2 "$SCRIPT"; } > "$SCRIPT_COPY"
chmod +x "$SCRIPT_COPY"

run_init() {
    local home="$1"
    OPT_DIR="$OPT" HOME="$home" AGENT_HOME="$home" bash "$SCRIPT_COPY"
}

# ---- Case 1: first boot ----
H1="$TMP/case1"
mkdir -p "$H1"
run_init "$H1"
test -f "$H1/.crontab"                              || { echo "case1: ~/.crontab not created"; exit 1; }
grep -q '^# >>> agent-images managed' "$H1/.crontab" || { echo "case1: begin sentinel missing"; exit 1; }
grep -q '^# <<< agent-images managed' "$H1/.crontab" || { echo "case1: end sentinel missing"; exit 1; }
grep -q "$H1/.local/bin"               "$H1/.crontab" || { echo "case1: __AGENT_HOME__ not substituted"; exit 1; }
grep -q '/opt/vk-bridge/run.sh'        "$H1/.crontab" || { echo "case1: bridge line missing"; exit 1; }
echo "case1: first-boot render OK"

# ---- Case 2: re-render with sentinels + preserved user content ----
H2="$TMP/case2"
mkdir -p "$H2"
cat > "$H2/.crontab" <<'EOF'
# user header — preserved
STALE_VAR=old-value
# >>> agent-images managed (regenerated on every boot — do not edit) >>>
SHELL=/bin/sh
PATH=/old/path
# old stale cron line — should be replaced
*/99 * * * * /opt/scripts/STALE.sh
# <<< agent-images managed <<<
# >>> chorebot (managed externally) >>>
0 4 * * * cd ~/repos/willikins/scripts/chorebot && python send-morning.py
# <<< chorebot <<<
# operator one-shot — preserved
0 9 1 1 * /home/agent/one-shot.sh
EOF
run_init "$H2"
grep -q '^# user header — preserved'          "$H2/.crontab" || { echo "case2: pre-sentinel user line lost"; exit 1; }
grep -q '^STALE_VAR=old-value'                 "$H2/.crontab" || { echo "case2: pre-sentinel env override lost"; exit 1; }
! grep -q '/opt/scripts/STALE.sh'              "$H2/.crontab" || { echo "case2: stale managed line not replaced"; exit 1; }
! grep -q '^PATH=/old/path'                    "$H2/.crontab" || { echo "case2: stale managed env not replaced"; exit 1; }
grep -q '/opt/vk-bridge/run.sh'                "$H2/.crontab" || { echo "case2: fresh managed bridge line missing"; exit 1; }
grep -q "$H2/.local/bin"                       "$H2/.crontab" || { echo "case2: __AGENT_HOME__ not substituted in re-render"; exit 1; }
grep -q '^# >>> chorebot'                      "$H2/.crontab" || { echo "case2: chorebot block lost"; exit 1; }
grep -q 'one-shot.sh'                          "$H2/.crontab" || { echo "case2: operator one-shot lost"; exit 1; }
[ "$(grep -c '^# >>> agent-images managed' "$H2/.crontab")" = "1" ] || { echo "case2: managed block not unique"; exit 1; }
echo "case2: re-render-with-sentinels OK"

# ---- Case 3: legacy ~/.crontab without sentinels is left alone ----
H3="$TMP/case3"
mkdir -p "$H3"
cat > "$H3/.crontab" <<'EOF'
SHELL=/bin/bash
PATH=/legacy/path
*/2 * * * * /legacy/path/bridge.py >> /legacy/log 2>&1
EOF
BEFORE="$(shasum -a 256 "$H3/.crontab" 2>/dev/null || sha256sum "$H3/.crontab")"
run_init "$H3"
AFTER="$(shasum -a 256 "$H3/.crontab" 2>/dev/null || sha256sum "$H3/.crontab")"
[ "${BEFORE%% *}" = "${AFTER%% *}" ] || { echo "case3: legacy ~/.crontab mutated unexpectedly"; exit 1; }
echo "case3: legacy-file-leave-alone OK"

echo "all tests passed"
