# Journal: 2026-07-23--agents--agent-images-version-sweep

<!-- fr:journal kind=finding scope=plan id=f1-micromamba-false-positive created=2026-07-23T18:42:54 phase=1 state=fixed -->
### f1-micromamba-false-positive · finding [fixed] · Audit reported micromamba BEHIND on a packaging-revision suffix (phase 1)

First live run flagged MICROMAMBA_VERSION 2.8.1 -> 2.8.1-0 as BEHIND. The -0 is a packaging revision, not a new version; the pin is current. A drift report with false positives stops being read, so version comparison now strips a trailing -<digits> ONLY (an alphanumeric prerelease like -rc1 still reads as drift). Two tests added.

<!-- fr:journal kind=decision scope=plan id=d6-ci-job created=2026-07-23T18:42:55 phase=1 -->
### d6-ci-job · decision · Added a test-scripts CI job (scope addition) (phase 1)

The plan wrote scripts/tests/ but CI had no job running them - the coverage guard (a version-shaped ARG with no PIN_SPECS entry) would never have fired. Added a test-scripts job mirroring the existing per-image test jobs. Small scope addition, defended at PR time.
