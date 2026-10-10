# Journal: 2026-10-10-agent-session-once

<!-- fr:journal kind=repro scope=debug id=83a4d51c88d6 created=2026-10-10T18:12:24+00:00 -->
### 83a4d51c88d6 · repro · #152 repro harness: real driver submit()+poll vs live claude 2.1.296 REPL in tmux

Host-side (devcontainer lacks tmux/claude). Driver module loaded via SourceFileLoader, ensure_session bypassed (no pretrust), Enter keypresses traced. Task: append one line to a ledger file. Control SETTLE_S=0.5: 1 Enter, 1 ledger line.

<!-- fr:journal kind=ruled-out scope=debug id=a5f121694e84 created=2026-10-10T18:12:31+00:00 -->
### a5f121694e84 · ruled-out · Verified-retry 2nd Enter does NOT re-run the turn (claude 2.1.296)

SETTLE_S=0.03 reproduces the unrepainted-box race: submit() sends 2 Enters 90ms apart, 2/2 runs. Ledger got exactly 1 line each run; pane shows ONE user message + ONE Bash call per turn. The bare Enter lands in an already-empty prompt and is a no-op. The issue's lead hypothesis is falsified as the doubling mechanism.

<!-- fr:journal kind=hypothesis scope=debug id=f1a917e6a787 created=2026-10-10T18:13:10+00:00 -->
### f1a917e6a787 · hypothesis · OPEN — #152 doubling: three candidates, none confirmable from this repo

With the retry-Enter falsified, the doubling must come from (H2) a second request reaching the node: a cncd retry with no or an unstable Idempotency-Key (send_idempotent only dedupes a stable key), (H3) a later wake on the SAME persistent session re-doing work still visible in context (the #157 class), or (H4) claude repeating the side-effecting call within one turn (e.g. a CNC POST that succeeded server-side but timed out client-side, then retried). cncd source is not reachable and there is no frank kube context, so the live transcript cannot be read. Discriminator: in the spec-b session's ~/.claude/projects/-home-*/<uuid>.jsonl, count user messages and comment-POST tool_uses: 1 user + 2 POSTs = H4; 2 user msgs with the same text = H2; 2 user msgs with different text = H3. #157 (fresh flag) is an independent feature regardless.
