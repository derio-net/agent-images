# Parallel Dispatch DAG — Bridge Audit Implementation Plan

## Phase 1: Bridge audit + fan-in regression test

### Task 1: Multi-blocker unit test for `check_blockers`

- P1.T1.S1: Read the two functions and note the contract

- P1.T1.S2: Write failing regression tests for multi-blocker `check_blockers`

- P1.T1.S3: Run the tests to observe the result

- P1.T1.S5: Run the full bridge test suite to confirm no regressions

- P1.T1.S6: Commit

### Task 2: Main-loop integration test — defer before slot allocation

- P1.T2.S1: Write a failing integration test for the defer-before-slot ordering

- P1.T2.S2: Run the test to observe the result

- P1.T2.S5: Run the full bridge test suite

- P1.T2.S6: Commit
