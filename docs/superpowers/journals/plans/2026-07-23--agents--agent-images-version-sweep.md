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

<!-- fr:journal kind=finding scope=plan id=f5-overspecific-test created=2026-07-23T18:57:20 phase=5 state=fixed -->
### f5-overspecific-test · finding [fixed] · The audit's own NODE_MAJOR test hardcoded the current value (phase 5)

test_major_only_pin_is_not_dropped asserted current == '22', so the Node 24 bump failed it. The test's real intent is that a bare major (no dots) survives extraction where a semver-shaped regex would drop it - that is a SHAPE claim. Pinning the value makes the test fail on every legitimate bump, which trains people to edit tests rather than read them. Changed to assert .isdigit().

<!-- fr:journal kind=finding scope=plan id=f6-node24-clean created=2026-07-23T18:57:21 phase=5 state=fixed -->
### f6-node24-clean · finding [fixed] · Node 24 built clean; local build also live-confirmed the wave 1 + 2 bumps (phase 5)

base built on Node 24.18.0 with npm 11.16.0; claude-code 2.1.218 installed against it fine. The same build confirmed supercronic v0.2.47 and yq v4.53.3 in a real image. agent-shell-base stacked on top installed s6-overlay 3.2.3.2 (/package/admin/s6-overlay-3.2.3.2) and its /init booted the FULL service tree - sshd and supercronic started, cont-init and cont-finish hooks ran, services stopped in order - which is what the CI smoke jobs assert. So wave 3b did not need dropping.

<!-- fr:journal kind=finding scope=plan id=f7-hermes-patch-obsolete created=2026-07-23T19:21:51 phase=6 state=fixed -->
### f7-hermes-patch-obsolete · finding [fixed] · Branch build caught a THIRD local patch the risk assessment missed - now obsolete (phase 6)

The dispatched branch build failed on build-children(hermes-agent-shell): 'patch failed: agent/conversation_loop.py:4180 ... patch does not apply'. hermes-agent-shell carried a local hermes-autocontinue-chat-completions.patch that the spec's risk assessment never inventoried (it covered the seed marker and config schema, not the patch). The zero-fuzz git apply failed loudly exactly as its Dockerfile comment says it is designed to.

Investigated rather than rebased: upstream 0.19.0 REPLACED the hardcoded api_mode=='codex_responses' gate with a real config knob, intent_ack_continuation (agent_runtime_helpers.intent_ack_continuation_mode), four modes mirroring tool_use_enforcement - auto->codex_only (old behaviour), true/always->all (what our patch forced), false->off, list->per-model. So the patch is OBSOLETE, not broken: dropped it rather than rebasing.

CONSEQUENCE FOR FRANK: config.yaml needs agent.intent_ack_continuation: true to keep pre-0.19.0 behaviour. config.yaml is PVC state (manual-op orch-hermes-config-provider), so this is a manual follow-up, added to frank's plan. Without it Hermes silently reverts to codex-only continuation on the chat_completions path.

Verified locally: image builds, 'Hermes Agent v0.19.0 (2026.7.20)' (which also confirms the calver/semver mapping), marker 0.19.0+nopatches1, knob present in site-packages.

<!-- fr:journal kind=finding scope=plan id=f8-stale-smoke-assertion created=2026-07-23T19:35:44 phase=6 state=fixed -->
### f8-stale-smoke-assertion · finding [fixed] · The hermes smoke test asserted the retired patch - updated to check the config knob (phase 6)

After the image built, smoke-test-hermes-agent-shell failed on '✗ auto-continue patch not present in live venv': it grepped the live venv for the patched string api_mode in ("codex_responses", "chat_completions"), which is exactly what I removed. The test was verifying the OLD mechanism. Rewrote it to assert the replacement - def intent_ack_continuation_mode in agent_runtime_helpers.py - at the same $LIVE PVC-venv path the surrounding (passing) assertions use. The behaviour itself is now config (agent.intent_ack_continuation: true), PVC state Frank owns, so the image smoke can only prove the knob exists, not that it is set. Knob confirmed present at the baked seed path locally.
