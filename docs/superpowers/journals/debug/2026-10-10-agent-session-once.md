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

<!-- fr:journal kind=ruled-out scope=debug id=4bea7d22012c created=2026-10-11T06:44:30+00:00 -->
### 4bea7d22012c · ruled-out · H2 and H3 unlikely through cncd v0.18.0

cncd sends a wake-stable Idempotency-Key (wake-<id>) and only re-sends after non-2xx or started=false. The node's send_idempotent is keyed on that value alone and holds a per-key flock across the whole turn, so a retry during or after the turn replays the cached result. H3: cncd sets session_id=RunID, so every wake gets a fresh session (turn=1 on both Frank runs). Residual H2 hole: an incident build earlier than bfcd421 that predates the Idempotency-Key.

<!-- fr:journal kind=root-cause scope=debug id=734cd1fc3c3c created=2026-10-11T06:53:29+00:00 -->
### 734cd1fc3c3c · root-cause · #152: the harness can act after the driver's turn ends (background-task self-resume); most likely cause, unconfirmed for the July walk

The driver treats 'result file appeared' as the end of the turn but never fences the harness. A background task left running makes Claude Code inject a task-notification and run a self-initiated turn with full task context, with no send and no Enter. This is proven on Frank (run 0e31be85) and matches #152's signature. The operator accepted fixing it without the walk host's DB, which would have confirmed it (both duplicate comments sharing one created_by_run_id). #157 is a separate feature delivered alongside: same file, same 'turn lifetime' concern.

<!-- fr:journal kind=finding scope=debug id=aa2e99a4e325 created=2026-10-11T06:53:37+00:00 state=fixed -->
### aa2e99a4e325 · finding [fixed] · end_session post-turn fence + fresh per-request reset

Driver: in the _send_locked finally (under the per-session flock), end_session kills the tmux session after a turn, whether it succeeded or timed out, and skips /compact. serve() defaults end_session on for /v1/session/send, off for the legacy path and the CLI. fresh ORs into the idle-reset /clear condition (no-op when last_activity is None). Tests written first (5 RED, 2 guard tests already GREEN), then 50/50 in test_agent_session.py: fresh-clears-despite-recent, fresh-noop-new-session, end_session-kills-after-turn, -after-timeout, -skips-compaction, cli-keeps-session, v1-default-on/legacy-off/explicit-false-honoured. README contract documents both fields.

<!-- fr:journal kind=finding scope=debug id=c07bf4b73ca1 created=2026-10-11T07:06:27+00:00 state=fixed -->
### c07bf4b73ca1 · finding [fixed] · Fence verified live and hardened

Host, real claude 2.1.296, task with a run_in_background job (sleep 30, then append) and an instruction to append again when notified. CONTROL (no end_session): driver returned at +0s, bg fired at +26s, self-initiated notification turn appended at +34s, reproducing H5 locally. FENCED (first cut): no bg, no notified, but claude was still alive 1s after kill-session (idle claude exits in ~1s). HARDENED (_reap: wait, then SIGTERM, then SIGKILL on the pane process group): claude already gone when send() returns, no bg, no notified line. 55/55 in test_agent_session.py; 4 of the 5 new review tests fail against the prior driver.

<!-- fr:journal kind=review scope=debug id=031f8b04941b created=2026-10-11T07:06:29+00:00 -->
### 031f8b04941b · review · Code review (general-purpose reviewer): With fixes, no Critical

Important: (1) fence effect not shown live, so it was verified live and the process wait/escalation added; (2) legacy-alias divergence, so README /v1 migration note added (frank alert-agent and n8n confirmed on the legacy path); (3) no resume-after-kill test, now added. Minor: (4) null/string flags, fixed with strict booleans and null=unset on /v1; (5) pre-submit failure orphan, fixed by fencing the whole turn; (6) README resume overstated, qualified to claude; (8) submit() claim, now cites the journal id. Not done: (7) paired compaction control, because test_compacts_when_context_over_threshold already serves as the control.
