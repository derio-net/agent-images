#!/usr/bin/env bash
# link-agent-instructions.sh — fan a canonical $HOME/AGENTS.md out to the per-harness
# project-instruction filenames, so whichever agent harness the driver launches loads
# the SAME instructions (tools, persona, boundaries).
#
# AGENTS.md (the agents.md cross-tool standard) is read NATIVELY by codex, opencode,
# antigravity and pi — they need no symlink. The exceptions get one → AGENTS.md:
#   * claude  reads CLAUDE.md ONLY (never AGENTS.md natively)
#   * Copilot reads .github/copilot-instructions.md
# Extend via AGENT_INSTRUCTION_LINKS (space-separated `target=symlink-value`, value
# relative to the target's own dir) — e.g. add a harness that wants its own file.
#
# Idempotent + fail-open; NEVER clobbers a real (non-symlink) file a deployment
# mounted at one of these paths.
set -uo pipefail

src="$HOME/AGENTS.md"
if [ ! -e "$src" ]; then
    echo "= agent-instructions: no $src — nothing to fan out"
    exit 0
fi

LINKS="${AGENT_INSTRUCTION_LINKS:-CLAUDE.md=AGENTS.md .github/copilot-instructions.md=../AGENTS.md}"
for pair in $LINKS; do
    rel="${pair%%=*}"; val="${pair#*=}"
    tgt="$HOME/$rel"
    if [ -e "$tgt" ] && [ ! -L "$tgt" ]; then
        echo "= agent-instructions: $rel is a real file (mounted?) — leaving it"
        continue
    fi
    mkdir -p "$(dirname "$tgt")" 2>/dev/null || true
    if ln -sfn "$val" "$tgt" 2>/dev/null; then
        echo "✓ agent-instructions: $rel → $val"
    else
        echo "= agent-instructions: could not link $rel (skipping)"
    fi
done
exit 0
