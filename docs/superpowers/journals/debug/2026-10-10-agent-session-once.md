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

<!-- fr:journal kind=finding scope=debug id=8bf5fd1b1dfe created=2026-10-11T06:44:27+00:00 state=open -->
### 8bf5fd1b1dfe · finding [open] · Frank evidence: the July double-post walk predates Frank's CNC; its transcript, DB and logs are not on Frank

Gathered read-only by the frank session. agent-images#152 was filed 2026-07-18T15:34Z, but cnc-staging-vcluster was created 16:54Z the same day, and the first staging run is 07-20. Two later Frank agent-session runs (wake 3 on 07-20, wake 4 on 09-10) each posted exactly 1 comment, each delivered with attempts=0. cncd logs no /v1/session/send requests. The incident cannot be root-caused from Frank's data.

<!-- fr:journal kind=hypothesis scope=debug id=6c9e8bc0a94a created=2026-10-11T06:44:28+00:00 -->
### 6c9e8bc0a94a · hypothesis · H5 (proven to exist): a background-task notification self-resumes the harness AFTER the driver's turn ends

Run 0e31be85 transcript: claude launched a run_in_background poller mid-turn. It finished ~70s after the out file was written; Claude Code injected a <task-notification> user message and claude ran a second, self-initiated assistant turn with the full task in context. No cncd send, no driver Enter, and .turn stayed 1. That reproduces the #152 signature exactly (one send, one succeeded, side effects able to fire again). In that run the extra turn only summarised the output. Pre-#36 builds spent whole turns discovering the API, which makes background jobs more likely in the July walk. Unconfirmed for the incident.
