# Journal: 2026-07-23--agents--agent-images-version-sweep

<!-- fr:journal kind=finding scope=plan id=f1-micromamba-false-positive created=2026-07-23T18:42:54 phase=1 state=fixed -->
### f1-micromamba-false-positive · finding [fixed] · Audit reported micromamba BEHIND on a packaging-revision suffix (phase 1)

First live run flagged MICROMAMBA_VERSION 2.8.1 -> 2.8.1-0 as BEHIND. The -0 is a packaging revision, not a new version; the pin is current. A drift report with false positives stops being read, so version comparison now strips a trailing -<digits> ONLY (an alphanumeric prerelease like -rc1 still reads as drift). Two tests added.

<!-- fr:journal kind=decision scope=plan id=d6-ci-job created=2026-07-23T18:42:55 phase=1 -->
### d6-ci-job · decision · Added a test-scripts CI job (scope addition) (phase 1)

The plan wrote scripts/tests/ but CI had no job running them - the coverage guard (a version-shaped ARG with no PIN_SPECS entry) would never have fired. Added a test-scripts job mirroring the existing per-image test jobs. Small scope addition, defended at PR time.

<!-- fr:journal kind=finding scope=plan id=f2-hermes-halves-skewed created=2026-07-23T18:49:12 phase=3 state=fixed -->
### f2-hermes-halves-skewed · finding [fixed] · The two Hermes halves of the same pod were on DIFFERENT upstream releases (phase 3)

hermes-agent uses calver git/docker tags but semver on PyPI. Mapping the two: v2026.5.29.2=0.15.2, v2026.7.7.2=0.18.2, v2026.7.20=0.19.0. So before this sweep hermes-agent-shell (PyPI 0.15.2 = v2026.5.29.2) and hermes-agent-shell-ssh (docker v2026.7.7.2 = 0.18.2) - two containers in the SAME deployment - were running upstream releases seven weeks apart. Nothing surfaced this because the two pins look like different products. Both now land on v2026.7.20 = 0.19.0. The dual-versioning scheme is the trap; the audit script's per-pin source refs make it visible.

<!-- fr:journal kind=finding scope=plan id=f3-hermes-config-schema-survives created=2026-07-23T18:49:13 phase=3 state=fixed -->
### f3-hermes-config-schema-survives · finding [fixed] · Frank's pinned hermes config keys all survive 0.15.2 -> 0.19.0 (phase 3)

hermes_cli/config.py grew 5849 -> 9232 lines (+58%) across the range, so the jump is substantial. Every key Frank depends on is still present: context_length (16->17), tool_loop_guardrails (1->1), hard_stop_enabled (1->1), provider (257->381), model (54->72). requires_python is <3.14,>=3.11, so the Dockerfile's --python 3.11 venv is still admissible. Risk is contained but not zero given the file's growth - live verification of provider resolution and context_length stays in the Test Plan.

<!-- fr:journal kind=finding scope=plan id=f4-ruflo-patches-apply created=2026-07-23T18:52:36 phase=4 state=fixed -->
### f4-ruflo-patches-apply · finding [fixed] · Both ruflo local patches apply cleanly at the new ref (locally proven) (phase 4)

docker build --target source at 26c35b5 succeeded: the sed wasm allow-line applied and its grep guard passed (step 4/6), and git apply of rvf-gridfs-parity.patch succeeded with all three grep guards passing (step 6/6). Premises independently re-verified before the bump: sed anchor present, wasm: still rejected upstream, rvf.ts still lacks new Writable / Readable.from / next: async, PR 2293 still open+unmerged. Blast radius re-measured by blob SHA: 501->501 blobs, zero paths added/removed, one content change (mcp-bridge/index.js). New ref is the 'bump ruflo to 3.32.9' release commit.
