# vk-local Memory Profiling Implementation Plan

## Phase 1: Workload survey & tooling check

### Task 1: Characterize what vk-local actually runs

- P1.T1.S1: Identify the vibe-kanban binary's vintage

- P1.T1.S2: List the binary's linked libraries

- P1.T1.S3: Enumerate HTTP surface under load

- P1.T1.S4: Draft the findings doc skeleton

### Task 2: Verify Prometheus + Grafana instrumentation

- P1.T2.S1: Confirm kube-state-metrics tracks the vk-local container

- P1.T2.S2: Confirm OOMKill events are tracked

- P1.T2.S3: Check if node-exporter tracks cgroup-level memory for this container

## Phase 2: Observation window

### Task 1: Run the 24h data collection

- P2.T1.S1: Record pre-window snapshot

- P2.T1.S2: Set up a lightweight in-pod sampler

- P2.T1.S3: Take 6 manual RSS snapshots over 24h (every 4h)

- P2.T1.S4: At T+24h, export the VictoriaMetrics time-series

- P2.T1.S5: Correlate with OOMKills

### Task 2: Activity correlation

- P2.T2.S1: Count kali audit log entries in the window

- P2.T2.S2: Hour-bucket audit activity and RSS

## Phase 3: Analysis & recommendation

### Task 1: Classify the memory pattern

- P3.T1.S1: Plot RSS over the window

- P3.T1.S2: Compute the recommendation number

### Task 2: Write the report & commit

- P3.T2.S1: Fill all empty sections of the findings doc

- P3.T2.S2: Commit on a feature branch

- P3.T2.S3: Open PR with the recommendation summary in the body

### Task 3: Close the loop on the umbrella issue

- P3.T3.S1: Comment on `derio-net/agent-images#2`
