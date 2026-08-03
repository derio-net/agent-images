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

<!-- fr:journal kind=finding scope=plan id=r1-vacuous-dockerfile-guards created=2026-08-03T18:00:11 state=fixed -->
### r1-vacuous-dockerfile-guards · finding [fixed] · Review: 4 of 6 Dockerfile guards bypassed the comment-stripping mitigation — the whole pytest layer was vacuous

Adversarial review proved it rather than asserting it: a doctored tree ('rev5') with NO checksum verification, NO architecture derivation, NO chmod of the shim, and bun installed under the PVC behind a symlink that dangles at runtime passed 58/58. Every failure mode the module docstring calls 'load-bearing and silent when wrong'.

Cause: the file defined _dockerfile_instructions() specifically to avoid matching its own explanatory comments, then used it in only 2 of 6 guards; the other 4 read raw text and so matched the comment block that NAMES SHASUMS256.txt, dpkg --print-architecture and the shim filename. The mitigation existed and was mostly unused — worse than not having it, because the docstring advertised it.

Fixed: every Dockerfile guard now reads _dockerfile_instructions(). Verified by re-running the FIXED tests against the reviewer's three doctored trees: rev 0->2 failures, rev2 0->2, rev5 0->4, while the real tree stays 58 passed.

<!-- fr:journal kind=finding scope=plan id=r2-mutation-test-reimplemented-guard created=2026-08-03T18:00:13 state=fixed -->
### r2-mutation-test-reimplemented-guard · finding [fixed] · Review: the 'actually catches a violation' test re-implemented the guard instead of calling it

It built an offending line then re-ran the predicate inline, so deleting the guard entirely left it green — it asserted that Python's 'in' operator works. Third instance in this repo of the pattern its own docstring cites.

Fixed by extracting _pvc_violations(text) and having BOTH the guard and the mutation check call it.

That refactor immediately earned its keep by exposing a REAL blind spot in the guard: 'RUN curl -fsSL https://bun.sh/install | bash' contains no PVC token at all — the danger is implicit in the installer's default target (/Users/derio/.bun) — so a token-matching guard could never see the single most likely regression. The guard now has a second rule for the installer URL (violation unless BUN_INSTALL points outside the mount), with negative controls for the legitimate install and for base/Dockerfile's redirected call. My own first version of this test FAILED against my own implementation, which is how the gap surfaced.

<!-- fr:journal kind=finding scope=plan id=r3-shim-mode-name-contradiction created=2026-08-03T18:00:14 state=fixed -->
### r3-shim-mode-name-contradiction · finding [fixed] · Review: test named '…is_made_executable…' inspected a line setting 0644, via a substring match

Two defects in one: the assertion was 'filename appears anywhere in the raw text' (so a mention in a COMMENT satisfied it), and the name asserted the opposite of the code. Reviewer verified 0644 is functionally fine — Debian's /etc/profile sources drop-ins via run-parts --list --regex, which tests -r not -x — but every sibling image in this repo (hermes-agent-shell, ruflo-shell, infra-shell) chmod +x its profile.d files.

Resolved toward the family convention: Dockerfile now chmod +x, test renamed to test_the_shim_mode_is_set_by_the_build and asserts the actual chmod line by regex. Confirmed in the rebuilt image: -rwxr-xr-x. An unexplained deviation from a convention is a trap for the next reader even when it works.

<!-- fr:journal kind=finding scope=plan id=r4-minor-review-fixes created=2026-08-03T18:00:16 state=fixed -->
### r4-minor-review-fixes · finding [fixed] · Review minors: AVX2 assumption, checksum overclaim, vacuous CI clause, second unpinned bun, report cosmetics

All actioned:

- AVX2: bun-linux-x64 requires AVX2 (bun's own installer falls back to -baseline without it). Frank's fleet includes pc-1 (i5-3570K, Ivy Bridge, no AVX2) where this would SIGILL at runtime while the build stayed green on an AVX2 CI runner. Cannot bite today — the pod is pinned to gpu-1 — but nothing recorded the dependency. Now stated in the Dockerfile with the fix if it is ever rescheduled. Kept x64 rather than degrading to baseline, since the node selector makes it a documented assumption rather than a live risk.
- Checksum overclaim: SHASUMS256.txt is fetched unauthenticated from the same origin as the asset, so it defends against corruption, NOT a replaced release. The comment framed choosing it over a pinned digest as superior; it is an ergonomics tradeoff. Reworded. (The reviewer separately PROVED the check is not vacuous: absent/misnamed/unlisted asset gives 'no file was verified' + exit 1, and set -e propagates into the subshell and the case.)
- CI clause was vacuous alone: 'command -v bun' prints nothing when absent, so the empty string fell to the *) branch and PASSED. Now requires a non-empty path first.
- base/Dockerfile installs a SECOND bun, unpinned via curl|bash with no ARG, invisible to find_uncovered_version_args. The PIN_SPECS note implied full coverage; it now says one of two.
- Report rendered the raw target, so a correct pin read '1.3.14 -> bun-v1.3.14 [ok]' and looked like drift. Now renders the prefix-stripped target.
