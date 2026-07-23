# agent-images Upstream Version Sweep

Spec: `derio-net/frank:docs/superpowers/specs/2026-07-23--agents--agent-images-upstream-version-sweep-design.md`

## What this plan does

Every version-bearing pin in this repo was measured against its upstream registry on 2026-07-23.
There is no watcher, so all of it had drifted untracked. This plan (a) builds the on-demand audit
script that makes the next sweep cheap, and (b) moves the pins the operator selected — the full
sweep, including the ruflo re-vendor and Node 24.

## Why the order is what it is

The waves are sequenced by **blast radius and by whether a failure should be allowed to block
anything else**, not by how interesting the change is:

- **Phase 1 (audit script)** comes first because it encodes the two non-obvious targeting rules
  (`talosctl` tracks the cluster, `omnictl` tracks the Omni server — not "latest"), and those rules
  are what Phase 2 then applies.
- **Phase 2 (Wave 1)** carries the one genuine *correctness* fix in the sweep. `talosctl` shipped
  v1.9.5 against a v1.12.6 cluster — three minors of skew, outside Talos's supported ±1. Everything
  else in this wave is patch-level with a contained failure mode.
- **Phase 3 (Wave 2)** is the wide-blast-radius pair. s6-overlay is PID 1 in every shell; a
  regression stops containers booting rather than degrading a feature. Hermes crosses four minors
  into a venv that lives on the PVC behind a `.seed-version` marker, so "the image ships 0.19.0" and
  "the pod runs 0.19.0" are different claims and only the second one matters.
- **Phase 4 (Wave 3a, ruflo)** looked like the scariest item and measured as one of the safest —
  see below. It is independent of the base-image tree, hence `depends_on: [1]` rather than [3].
- **Phase 5 (Wave 3b, Node 24)** is last and deliberately droppable: it is the only pin in the sweep
  with no correctness driver behind it, and it rebases the runtime under everything.
- **Phase 6** exists because CI will not do it for us (see below).
- **Phase 7** is the single manual phase, back-loaded so nothing agentic waits on it.

## The ruflo headline is wrong, and the measurement is the interesting part

"607 commits behind" is a monorepo artifact. `ruvnet/ruflo` is a monorepo; this repo builds only the
`ruflo/src/ruvocal/` subtree. Measured at that subtree across the range: **501 blobs at both refs,
no additions, no removals, exactly one changed file** — `mcp-bridge/index.js`.

Two traps are worth carrying forward, both encoded as steps in Phase 4:

1. **The compare API caps `.files[]` at 300 entries.** A `grep` over that truncated list reports
   *zero* ruvocal changes — a confident false negative. Comparing tree SHAs, then blob SHAs, is the
   only sound way to diff a subtree across a large range.
2. **Both local patch targets are byte-identical across the range**, so the `wasm:` `sed` and
   `rvf-gridfs-parity.patch` still apply — and are still *required*, because upstream PR
   `ruvnet/ruflo#2293` is **open, not merged**. Two comments in the Dockerfile currently imply
   otherwise and are corrected in this plan.

The one changed file is an ADR-166 security fix closing a disclosed unauthenticated RCE chain
(default-deny `terminal_execute`, loopback bind, bearer auth, CORS allowlist). It is not shipped in
the runtime image — the runtime stage copies only `/app/build`, `node_modules`, `.env`,
`entrypoint.sh`, `package.json` — so for Frank's deployed artifact this bump is close to a
functional no-op that removes a known-vulnerable file from the build context.

Residual risk that no pin controls: `package.json` is byte-identical, so its semver ranges resolve
to whatever npm publishes **at build time**. Every rebuild in this plan moves transitive
dependencies. That is a property of the image, not of this bump — the `ruflo-server` smoke test is
what catches it.

## CI will not validate this PR

`build.yaml` triggers on **push to `main` only** (with `paths-ignore: docs/**`),
`workflow_dispatch`, and `repository_dispatch` — **never on `pull_request`**. So neither opening the
PR nor pushing the branch builds anything. Phase 6 dispatches the build explicitly with
`gh workflow run build.yaml --ref <branch>`; without it, this PR is green-looking and entirely
unverified. The per-image smoke jobs it runs (each asserting `/init` boots under a K8s-equivalent
securityContext) are the control that makes waves 2 and 3 acceptable risks at all.

## Two pin classes

Bootstrap pins (`claude-code`, `codex`, `opencode`) are first-boot seeds only — the CLI self-updates
in-pod and floats forward via the inventory `harnesses:` key. Bumping them changes what a *fresh*
PVC starts from and nothing else. Rebuild-only pins (everything else) have the image rebuild as
their sole refresh path; that is where staleness became a real problem. The audit script encodes
this split so its report ranks by what actually matters rather than by how many releases behind a
pin happens to be.

## Not in scope

`MICROMAMBA_VERSION`, `TORCH_VERSION`, `TMUX_RESURRECT_REF`, `TMUX_CONTINUUM_REF` are already at
upstream latest. `BGE_REVISION` is a HuggingFace *model* revision — bumping it changes embedding
behaviour and belongs to a Hindsight-quality decision, not a version sweep. `VK_FORK_SHA` is built
from our own fork by a separate pipeline. `agy`, `kubectl` (fetched from `stable.txt`) and the
unpinned `claude-code` float on every rebuild regardless — untracked variables this plan does not
attempt to fix, but which every rebuild here silently moves.
