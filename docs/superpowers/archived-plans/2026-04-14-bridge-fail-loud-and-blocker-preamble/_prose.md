# Bridge Fail Loud And Blocker Preamble Implementation Plan

## Phase 0: Test bootstrap and fail-loud parse_dependencies

### Task 1: Bootstrap test harness for the bridge

- P0.T1.S1: Confirm test layout

- P0.T1.S2: Write initial import test

### Task 2: Fail loud when phase>0 has no parseable dependencies

- P0.T2.S1: Failing test — parse_dependencies gates on phase_number

- P0.T2.S2: Add phase_number parameter with fail-loud logic

- P0.T2.S3: Extend GhIssue with labels, update gh_list_ready_issues

- P0.T2.S4: Thread phase_number into main() parse_dependencies call

## Phase 1: Fail-loud check_blockers

### Task 1: Remove fail-open on gh errors

- P1.T1.S1: Failing tests — check_blockers raises on gh error

- P1.T1.S2: Rewrite check_blockers fail-loud

- P1.T1.S3: Handle RuntimeError at call site

## Phase 2: Blocker preamble in build_prompt

### Task 1: Prepend preamble when deps present

- P2.T1.S1: Failing tests — preamble presence contract

- P2.T1.S2: Extend build_prompt signature

- P2.T1.S3: Thread deps into sync_issue call

## Phase 3: Deploy bridge to production

### Task 1: Review, merge, deploy

- P3.T1.S1: Create PR and merge

- P3.T1.S2: Deploy updated script

- P3.T1.S3: Smoke test next cron tick

- P3.T1.S4: Verify deferral behavior on a live blocked Issue

- P3.T1.S5: Notify superpowers-for-vk Phase 5 to proceed
