# Persistent Agent Reliability Implementation Plan

## Phase 0: Remote-control close/list spike

### Task 1: Investigate Claude CLI for session/env management

- P0.T1.S1: Survey `claude` CLI surface

- P0.T1.S2: Inspect Claude state dir for env/session bookkeeping

- P0.T1.S3: Probe for a server-side disconnect endpoint

- P0.T1.S4: Test SIGTERM/SIGINT behavior in a sandbox

- P0.T1.S5: Write findings doc and commit

## Phase 1: Housekeeping batch

### Task 1: Failing test — audit hook writes to audit.jsonl

- P1.T1.S1: Confirm test layout

- P1.T1.S2: Write failing test for PostToolUse Bash audit write

### Task 2: Fix audit hook key mismatch

- P1.T2.S1: Inspect current payload key usage

- P1.T2.S2: Accept both keys, preferring the current one

- P1.T2.S3: Re-run tests

- P1.T2.S4: Smoke check against a real payload example

### Task 3: Log rotation for session-*.log

- P1.T3.S1: Write logrotate config

- P1.T3.S2: Write wrapper script

- P1.T3.S3: Verify logrotate is present in the image

- P1.T3.S4: Add hourly cron entry

- P1.T3.S5: Dry-run test

### Task 4: vk-bridge — skip repos with no GitHub remote-side presence

- P1.T4.S1: Read current behavior

- P1.T4.S2: Failing test — 404 on a repo should be demoted from warn to debug-or-silent

- P1.T4.S3: Downgrade 404 to info, keep other errors as warn

- P1.T4.S4: Re-run full bridge suite

### Task 5: Phase 1 PR

- P1.T5.S1: Open PR

## Phase 2: Graceful shutdown

### Task 1: Write shutdown script

- P2.T1.S1: Read Phase 0 decision

- P2.T1.S2: Write shutdown.sh skeleton (signal-based baseline)

- P2.T1.S3: Tests for shutdown.sh

### Task 2: Wire shutdown into session-manager + supercronic exit

- P2.T2.S1: Review entrypoint

- P2.T2.S2: Add trap in entrypoint.sh

- P2.T2.S3: Verify trap locally

### Task 3: K8s preStop hook (frank-side) — filed as separate Issue

- P2.T3.S1: Open a tracking Issue against derio-net/frank

- P2.T3.S2: Link in the plan

### Task 4: Phase 2 PR

- P2.T4.S1: Open PR

## Phase 3: 24h soak

### Task 1: Deploy

- P3.T1.S1: Merge Phase 1 and Phase 2 PRs

- P3.T1.S2: Rebuild image and roll pod

- P3.T1.S3: Capture baseline

### Task 2: Observe for 24h

- P3.T2.S1: Check at T+2h, T+8h, T+24h

- P3.T2.S2: Manual phantom count in claude.ai

### Task 3: Outcome note and follow-up decisions

- P3.T3.S1: Write outcome note

- P3.T3.S2: Open follow-up plans if needed

- P3.T3.S3: Mark Status complete
