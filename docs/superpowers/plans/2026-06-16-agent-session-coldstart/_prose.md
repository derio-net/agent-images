# agent-session cold-start reliability (Thread A)

The baked `agent-session` driver creates a tmux session and returns immediately, then pastes +
Enters after a fixed 0.5s. Empirically (captured against a real claude cold boot) the pane is
**completely empty** at 0.5–2s and the REPL prompt (`❯`) only renders ~6s in — so the first Enter is
dropped and the first turn times out. Warm turns work. This is the sole functional gap behind "the
agent doesn't answer the first DM".

Three changes, one file, stdlib-only, mirroring the existing tmux-mock test harness:

- **A1 readiness gate** (`wait_ready` in `ensure_session`, on session creation only): poll
  `capture-pane` until the `❯` prompt renders (or a non-empty pane goes stable — version-drift
  insurance), capped by `AGENT_SESSION_READY_TIMEOUT_S` (~30s) then best-effort proceed. Covers
  every lazily-created session id, not just one pre-warmed default.
- **A3 verified submit**: after the Enter, re-capture; if the message still sits in the input box,
  press Enter once more (single retry). The load-bearing fix — catches a cold pane AND any first-run
  auto-mode interstitial, regardless of whether the A1 marker is exactly right.
- **A2 pretrust flag**: seed `hasSeenAutoModeEntryWarning` next to the existing
  `hasTrustDialogAccepted`. Best-effort defence-in-depth; A3 is the guarantee.

## Why the `❯` marker, not pane-stability

The empirical capture showed the bottom status line (claude-mem token counts, worktree list) keeps
mutating for seconds *after* the REPL accepts input — so "pane unchanged across two polls" would wait
too long or never settle. The `❯` prompt glyph is the stable cold→ready signal; stability is only a
fallback for an agent/version that doesn't render it.

## Sequencing

This gates the frank `2026-06-16--obs--alert-agent-telegram-ux` plan's live smoke test only. Merge
this → CI builds a new `multi-agent-shell` tag → the frank PR bumps its `deployment.yaml` image SHA
to that tag → operator merges frank → the post-merge Test Plan proves a cold DM is answered with the
⚡/👍 reactions. The bridge UX changes do not require this image to function (the bridge talks to the
driver over HTTP; this change is internal to the driver).
