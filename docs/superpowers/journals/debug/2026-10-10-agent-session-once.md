# Journal: 2026-10-10-agent-session-once

<!-- fr:journal kind=repro scope=debug id=83a4d51c88d6 created=2026-10-10T18:12:24+00:00 -->
### 83a4d51c88d6 · repro · #152 repro harness: real driver submit()+poll vs live claude 2.1.296 REPL in tmux

Host-side (devcontainer lacks tmux/claude). Driver module loaded via SourceFileLoader, ensure_session bypassed (no pretrust), Enter keypresses traced. Task: append one line to a ledger file. Control SETTLE_S=0.5: 1 Enter, 1 ledger line.

<!-- fr:journal kind=ruled-out scope=debug id=a5f121694e84 created=2026-10-10T18:12:31+00:00 -->
### a5f121694e84 · ruled-out · Verified-retry 2nd Enter does NOT re-run the turn (claude 2.1.296)

SETTLE_S=0.03 reproduces the unrepainted-box race: submit() sends 2 Enters 90ms apart, 2/2 runs. Ledger got exactly 1 line each run; pane shows ONE user message + ONE Bash call per turn. The bare Enter lands in an already-empty prompt and is a no-op. The issue's lead hypothesis is falsified as the doubling mechanism.
