# Silent-Reconnect Phantom Reaper Implementation Plan

## Phase 0: Recon spike

### Task 1: Live-verify pointer survival, credentials, DELETE signature

- P0.T1.S1: Baseline inspection on the pod

- P0.T1.S2: Start a throwaway bridge

- P0.T1.S3: SIGKILL and verify pointer survival

- P0.T1.S4: Locate organization UUID

- P0.T1.S5: Compose and verify a working DELETE

- P0.T1.S6: TTL observation (non-gating)

- P0.T1.S7: Cleanup

- P0.T1.S8: Write findings doc

## Phase 1: Reaper implementation

### Task 1: Read Phase 0 decision and confirm branch

- P1.T1.S1: Confirm chosen branch

### Task 2: Failing tests for the reaper (Branch A — pointer-based)

- P1.T2.S1: Write the bash test harness _(skipped — Branch A; the equivalent test was authored in Task 4 against `$WILLIKINS_AGENT_DIR/envs/*.json` per Phase 0 findings.)_

### Task 3: Implement the reaper (Branch A)

- P1.T3.S1: Write `reap-orphan-envs.sh` _(skipped — Branch A pointer-based reaper; the Branch B variant scanning `$WILLIKINS_AGENT_DIR/envs/*.json` was authored in Task 4 Step 3.)_

- P1.T3.S2: Re-run the bash tests _(skipped — Branch A; covered by Task 4 Step 3's bash tests against the Branch B reaper.)_

- P1.T3.S3: Integrate into session-manager _(skipped — Branch A; the same integration is performed in Task 4 Step 4 alongside the wrapper spawn-line change.)_

- P1.T3.S4: Smoke test on the pod (post-build) _(deferred — runs after PR merges and the image is rebuilt; the Phase 2 soak exercises this path. Plan note: "Defer to Phase 2 for the soak-level acceptance.")_

### Task 4: Implement supervisor wrapper (Branch B — conditional)

- P1.T4.S1: Failing test for wrap-claude.py

- P1.T4.S2: Implement `wrap-claude.py`

- P1.T4.S3: Branch-B reaper variant

- P1.T4.S4: Update session-manager spawn line

### Task 5: Open PR

- P1.T5.S1: Verify all tests pass

- P1.T5.S2: Commit and push

## Phase 2: 48h soak

### Task 1: Deploy

- P2.T1.S1: Merge Phase 1 PR and build image

- P2.T1.S2: Roll the pod on Frank

- P2.T1.S3: Capture baseline

### Task 2: Observe for 48h

- P2.T2.S1: Checkpoint at T+8h

- P2.T2.S2: Checkpoint at T+24h

- P2.T2.S3: Checkpoint at T+48h

### Task 3: Outcome note and follow-up decisions

- P2.T3.S1: Post soak summary to agent-images#2

- P2.T3.S2: Trigger follow-up plans if needed

- P2.T3.S3: Mark plan status
