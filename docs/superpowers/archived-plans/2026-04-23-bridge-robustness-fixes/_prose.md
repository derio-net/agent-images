# Bridge Robustness Fixes Implementation Plan

## Phase 1: Accept explicit no-deps marker for any phase number

### Task 1: Widen the no-deps marker detection in `parse_dependencies`

- P1.T1.S1: TDD — add failing tests for the no-deps marker at any phase number

- P1.T1.S2: Implement the marker regex

- P1.T1.S3: Run the suite

## Phase 2: Archive workspace + close GitHub Issue on Done transition

### Task 1: Add `update_workspace` MCP client method

- P2.T1.S1: Expose the MCP `update_workspace` tool

### Task 2: Wire Done transitions to archive workspace + close GH Issue

- P2.T2.S1: TDD — `TestPollArchivesWorkspaceOnMerge`

- P2.T2.S2: TDD — `TestPollClosesGhIssueOnMerge`

- P2.T2.S3: Implement `archive_workspace_for_card(client, simple_id)`

- P2.T2.S4: Implement `close_gh_issue_for_card(title, pr_url)`

- P2.T2.S5: Wire both into `poll_pr_status`

- P2.T2.S6: Run the suite

## Phase 3: Reap orphan workspaces each cycle

### Task 1: Add `reap_orphan_workspaces` helper

- P3.T1.S1: TDD — `TestReapOrphanWorkspaces`

- P3.T1.S2: Implement `reap_orphan_workspaces(client)`

- P3.T1.S3: Call once per bridge cycle in `main()`

- P3.T1.S4: Run the full suite

## Phase 4: Commit
