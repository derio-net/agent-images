# Journal: 2026-08-03-hermes-ssh-bun-runtime

<!-- fr:journal kind=discovery scope=plan id=p1-bun-tag-prefix created=2026-08-03T17:36:06 phase=1 -->
### p1-bun-tag-prefix · discovery · bun tags releases 'bun-v1.3.14' — the audit would have reported a permanently BEHIND pin (phase 1)

Unplanned but required. version_audit resolves a github-release pin to its 'tag_name', and _normalise only strips a leading 'v' (plus a trailing packaging revision). bun's tag is 'bun-v1.3.14', so the pin '1.3.14' could never equal its own release tag and would have classified BEHIND from the day it was added — the exact false positive version_audit's own docstring says stops a report being read.

Fixed with a per-pin 'tag_prefix' (Pin field + extract_pins wiring + a strip in classify_status before normalisation), declared as 'bun-' on BUN_VERSION. Deliberately a DECLARED prefix rather than a general 'strip anything before the v' rule: two tests pin the behaviour in both directions — a current pin reads CURRENT against 'bun-v1.3.14', and a genuine bump still reads BEHIND against 'bun-v1.3.15', so the strip cannot silently blind the comparison.

<!-- fr:journal kind=finding scope=plan id=p1-tests-were-wrong-not-code created=2026-08-03T17:36:09 phase=1 state=fixed -->
### p1-tests-were-wrong-not-code · finding [fixed] · Three of my own RED tests were defective — one repeated a known repo failure mode (phase 1)

First green run left 3 failures, all test defects rather than implementation defects:

1. test_bun_is_not_installed_under_the_pvc_mount scanned RAW Dockerfile text, so it flagged the COMMENT that explains the trap (the block quoting ${AGENT_HOME} and /opt/data/home while telling you not to install there). Same root cause as the seed-source guard this repo already shipped that matched its own explanatory comment — there a false PASS, here a false FAIL, but identical mechanism. Fixed with a _dockerfile_instructions() helper that strips comment lines, and a companion test proving the matching logic still catches a real violation.
2. test_bun_is_installed_as_root_before_the_user_switch matched '^RUN .*bun.*$', which cannot see into a multi-line RUN — the install's bun references are all on continuation lines. It would have passed only for a one-line install. Now indexes the whole instruction text.
3. test_the_path_shim_is_idempotent asserted the literal string 'case ":$PATH:"' while the shim uses ${PATH}. Rather than loosen it to my brace style, it now EXECUTES the shim twice under bash and counts occurrences — behaviour instead of spelling. Added a sibling test that the shim is silent and non-failing when $HOME/.bun/bin does not exist yet (true before the operator's first install; a noisy profile.d entry greets every SSH login).

<!-- fr:journal kind=discovery scope=plan id=p2-runtime-proof created=2026-08-03T17:36:11 phase=2 -->
### p2-runtime-proof · discovery · Runtime proof against a built image, under the pod's securityContext (phase 2)

docker build succeeded; container run with --user 1000:1000 --cap-drop ALL. Observed:

- 'bun --version' -> 1.3.14
- 'command -v bun' -> /usr/local/bin/bun (outside every PVC mount)
- LOGIN shell PATH -> /opt/data/home/.bun/bin:/usr/local/bin:/usr/bin:/bin:... (the shim works where it must)
- re-sourcing the shim leaves exactly 1 occurrence
- the sshd entrypoint is still present and executable

NOT proven, and not claimed: a real 'bun install -g' — the container has no network egress for the registry in this harness. That the global install persists across a pod restart is a post-merge test-plan row (frank spec row 8), and it is the row that decides whether the install-at-runtime decision was right.

Environmental note: the first build failed with 'You don't have enough free space in /var/cache/apt/archives/' — Docker Desktop's VM disk, not the Dockerfile. 'docker builder prune -af' + 'image prune -af' reclaimed 10GB and the identical build then succeeded.

Also newly visible (NOT newly caused): 'bash -lc' in a bare container prints 'bash: /opt/data/home/.bash_profile: Permission denied', because $AGENT_HOME has no PVC mounted over it there. In the pod that path IS a PVC with fsGroup 1000. Nobody had run a login shell in this image before, so the message is new to observation, not new to the image.
