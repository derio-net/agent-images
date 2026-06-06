# vk-bridge Warn-Pattern Broadening Implementation Plan

## Phase 1: Broaden warn-demotion patterns

### Task 1: Failing tests for the new warn categories

- P1.T1.S1: Locate the existing warn-filtering class

- P1.T1.S2: Add failing test — GraphQL "Could not resolve to a Repository" is demoted

- P1.T1.S3: Add failing test — transient network errors are demoted to info

- P1.T1.S4: Add regression guard — real HTTP 5xx still warns

- P1.T1.S5: Run the new tests — all should fail (except the regression guard, which passes on current code)

### Task 2: Broaden the classifier

- P1.T2.S1: Read the existing classifier

- P1.T2.S2: Extract the pattern match into a module-level helper

- P1.T2.S3: Wire the helper into `gh_list_ready_issues`

- P1.T2.S4: Re-run the warn-filtering tests — all should pass

- P1.T2.S5: Run the full bridge suite — catch regressions

### Task 3: Direct-unit tests for `_classify_gh_error`

- P1.T3.S1: Add a class that exercises the classifier directly

- P1.T3.S2: Run the direct unit tests

### Task 4: Smoke-check against real log sample

- P1.T4.S1: Pull a sample of recent warn lines from the live pod

- P1.T4.S2: Cross-check each sampled stderr against the classifier

### Task 5: PR

- P1.T5.S1: Commit on a feature branch

- P1.T5.S2: Open PR and reference the soak observation

- P1.T5.S3: After merge, confirm observability in production
