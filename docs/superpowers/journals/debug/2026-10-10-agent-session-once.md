# Journal: 2026-10-10-agent-session-once

<!-- fr:journal kind=repro scope=debug id=83a4d51c88d6 created=2026-10-10T18:12:24+00:00 -->
### 83a4d51c88d6 · repro · #152 repro harness: real driver submit()+poll vs live claude 2.1.296 REPL in tmux

Host-side (devcontainer lacks tmux/claude). Driver module loaded via SourceFileLoader, ensure_session bypassed (no pretrust), Enter keypresses traced. Task: append one line to a ledger file. Control SETTLE_S=0.5: 1 Enter, 1 ledger line.
