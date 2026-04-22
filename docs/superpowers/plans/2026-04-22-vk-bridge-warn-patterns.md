# vk-bridge Warn-Pattern Broadening Implementation Plan

> **For VK agents:** Use vk-execute to implement assigned phases.
> **For local execution:** Use subagent-driven-development or executing-plans.
> **For dispatch:** Use vk-dispatch to create Issues from this plan.

**Spec:** `docs/superpowers/specs/2026-04-18-persistent-agent-reliability-design.md`
**Status:** Not Started

**Goal:** Broaden `kali/scripts/vk-issue-bridge.py`'s warn-demotion error classification to cover GraphQL-layer "Could not resolve to a Repository" errors and transient network flakes, so the pod stops emitting ~65 spurious `[warn]` lines per hour into `vk-bridge.log`.

**Context:** During the T+48h soak of `docs/superpowers/plans/2026-04-18-persistent-agent-reliability.md` Phase 3, the Phase 1 Task 4 fix was found insufficient. The fix at `kali/scripts/vk-issue-bridge.py:383` matches REST `HTTP 404` and `Could not resolve` on REST responses. Observed production warns:

| Count | Pattern | Matched by current fix? |
|---|---|---|
| 2948 | `gh issue list failed for derio-net/derio-profile: GraphQL: Could not resolve to a Repository` | **No** — GraphQL-layer error, stderr format differs |
| ~100 | `HTTP 5xx: Bad Gateway` / `Bad Request` | No — only 404 is demoted, 5xx is "real" transient |
| ~70 | `Post "https://api.github.com/graphql": unexpected EOF` | No — network flake |
| ~10 | `Post "…": read: connection reset by peer` | No — network flake |

**Architecture:** One-file change in `kali/scripts/vk-issue-bridge.py` (the error classifier in `gh_list_ready_issues`). Tests extend the existing `TestDiscoveryWarningFiltering` class in `kali/tests/test_vk_issue_bridge.py:857`.

**Tech Stack:** Python 3.11+, pytest, `gh` CLI (mocked via monkeypatched `subprocess.run`).

**Scope boundary:** This plan *only* reclassifies log noise. It does not change retry behavior, does not add alerting on the "real" warn categories, and does not filter the repo discovery to skip phantom repos. Those are out of scope.

---

## Phase 1: Broaden warn-demotion patterns [agentic]

**Depends on:** —

### Task 1: Failing tests for the new warn categories

**Files:**
- Modify: `kali/tests/test_vk_issue_bridge.py`

- [ ] **Step 1: Locate the existing warn-filtering class**

```bash
grep -n "class TestDiscoveryWarningFiltering" kali/tests/test_vk_issue_bridge.py
```

Expected: one match near line 857. Confirm the class uses `monkeypatch.setattr(_subprocess, "run", fake_run)` to stub `gh` failure stderr.

- [ ] **Step 2: Add failing test — GraphQL "Could not resolve to a Repository" is demoted**

Extend `TestDiscoveryWarningFiltering` with:

```python
    def test_gh_graphql_could_not_resolve_is_info_not_warn(self, monkeypatch, capsys):
        """GraphQL-layer 'Could not resolve to a Repository' is the same condition
        as REST HTTP 404 — local-only mirror, not a real failure. The Phase 1
        fix only caught the REST form; this extends it."""
        monkeypatch.setattr(mod, "discover_repos", lambda *a, **kw: ["derio-profile"])

        def fake_run(*args, **kwargs):
            raise _subprocess.CalledProcessError(
                1, "gh",
                stderr=(
                    "GraphQL: Could not resolve to a Repository with the name "
                    "'derio-net/derio-profile'. (repository)"
                ),
            )
        monkeypatch.setattr(_subprocess, "run", fake_run)

        issues = mod.gh_list_ready_issues()
        assert issues == []

        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "[warn]" not in combined
        assert "[info]" in combined
```

- [ ] **Step 3: Add failing test — transient network errors are demoted to info**

Add two test cases covering `unexpected EOF` and `connection reset by peer`:

```python
    def test_gh_transient_eof_is_info_not_warn(self, monkeypatch, capsys):
        """GitHub API flakes (EOF, reset) should not alert — the bridge runs
        every 2 min and will retry naturally. Warn noise drowns real issues."""
        monkeypatch.setattr(mod, "discover_repos", lambda *a, **kw: ["willikins"])

        def fake_run(*args, **kwargs):
            raise _subprocess.CalledProcessError(
                1, "gh",
                stderr='Post "https://api.github.com/graphql": unexpected EOF',
            )
        monkeypatch.setattr(_subprocess, "run", fake_run)

        issues = mod.gh_list_ready_issues()
        assert issues == []

        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "[warn]" not in combined
        assert "[info]" in combined

    def test_gh_transient_reset_is_info_not_warn(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "discover_repos", lambda *a, **kw: ["willikins"])

        def fake_run(*args, **kwargs):
            raise _subprocess.CalledProcessError(
                1, "gh",
                stderr=(
                    'Post "https://api.github.com/graphql": read tcp '
                    "10.244.10.125:40904->140.82.121.5:443: read: connection "
                    "reset by peer"
                ),
            )
        monkeypatch.setattr(_subprocess, "run", fake_run)

        issues = mod.gh_list_ready_issues()
        assert issues == []

        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "[warn]" not in combined
        assert "[info]" in combined
```

- [ ] **Step 4: Add regression guard — real HTTP 5xx still warns**

This is the "do not over-demote" test. A 502/503 is a real upstream problem worth surfacing. Add:

```python
    def test_gh_http_5xx_still_warns(self, monkeypatch, capsys):
        """HTTP 5xx from GitHub is a real upstream problem — do not demote
        it. If this fires frequently, operators need to know."""
        monkeypatch.setattr(mod, "discover_repos", lambda *a, **kw: ["frank"])

        def fake_run(*args, **kwargs):
            raise _subprocess.CalledProcessError(
                1, "gh",
                stderr="HTTP 503: Service Unavailable",
            )
        monkeypatch.setattr(_subprocess, "run", fake_run)

        issues = mod.gh_list_ready_issues()
        assert issues == []

        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "[warn]" in combined
```

- [ ] **Step 5: Run the new tests — all should fail (except the regression guard, which passes on current code)**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images/kali
python -m pytest tests/test_vk_issue_bridge.py::TestDiscoveryWarningFiltering -x -v 2>&1 | tail -30
```

Expected: the existing `test_gh_404_is_info_not_warn` passes (Phase 1 fix is live). The three new demotion tests FAIL — they hit the `[warn]` branch. The regression-guard test `test_gh_http_5xx_still_warns` passes (a 5xx stderr doesn't match current regex, so it already warns).

### Task 2: Broaden the classifier

**Files:**
- Modify: `kali/scripts/vk-issue-bridge.py`

- [ ] **Step 1: Read the existing classifier**

```bash
sed -n '380,395p' kali/scripts/vk-issue-bridge.py
```

Expected: the `except subprocess.CalledProcessError` block at line 381–388 with the current regex `re.search(r"\bHTTP 404\b", stderr) or "Could not resolve" in stderr`.

- [ ] **Step 2: Extract the pattern match into a module-level helper**

Keeping the classification logic inline makes it hard to test in isolation and hard to extend. Move it to a helper. Add near the top of the file's internal helpers section (after the existing constants, before `push_success_metric`):

```python
# --- Error classification ---

# Stderr patterns that indicate "the repo isn't on GitHub" — expected for
# local-only mirrors and phantom directories in ~/repos/. Not worth a warn.
_ABSENT_REPO_PATTERNS = (
    re.compile(r"\bHTTP 404\b"),
    re.compile(r"Could not resolve(?: to a Repository)?", re.IGNORECASE),
)

# Stderr patterns that indicate GitHub or the network flaked. The bridge
# runs every 2 min and retries naturally; single-shot failures are noise.
_TRANSIENT_NETWORK_PATTERNS = (
    re.compile(r"unexpected EOF"),
    re.compile(r"connection reset by peer"),
    re.compile(r"i/o timeout"),
    re.compile(r"no such host"),  # DNS blip on the pod
)


def _classify_gh_error(stderr: str) -> str:
    """Classify a `gh` CLI stderr into a log level.

    Returns 'info' for expected/transient conditions, 'warn' for anything
    that could indicate a real problem (auth, 5xx, malformed response)."""
    for pat in _ABSENT_REPO_PATTERNS:
        if pat.search(stderr):
            return "info"
    for pat in _TRANSIENT_NETWORK_PATTERNS:
        if pat.search(stderr):
            return "info"
    return "warn"
```

- [ ] **Step 3: Wire the helper into `gh_list_ready_issues`**

Replace lines 381–388 (`except subprocess.CalledProcessError as e:` block) with:

```python
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            level = _classify_gh_error(stderr)
            first_line = stderr.splitlines()[0] if stderr else ""
            if level == "info":
                log(f"[info] gh list skipped — {repo}: {first_line}")
            else:
                log(f"[warn] gh issue list failed for {repo}: {stderr}")
            continue
```

- [ ] **Step 4: Re-run the warn-filtering tests — all should pass**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images/kali
python -m pytest tests/test_vk_issue_bridge.py::TestDiscoveryWarningFiltering -x -v 2>&1 | tail -15
```

Expected: all five tests pass (the existing 404 test, three new demotion tests, one regression guard).

- [ ] **Step 5: Run the full bridge suite — catch regressions**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images/kali
python -m pytest tests/test_vk_issue_bridge.py -x 2>&1 | tail -10
```

Expected: pass. If any unrelated test fails, STOP — the helper extraction changed something it shouldn't have.

### Task 3: Direct-unit tests for `_classify_gh_error`

**Files:**
- Modify: `kali/tests/test_vk_issue_bridge.py`

- [ ] **Step 1: Add a class that exercises the classifier directly**

The `TestDiscoveryWarningFiltering` tests above exercise the full `gh_list_ready_issues` path (integration-style). Add a narrower class that hits only the classifier — this catches regex mistakes without the subprocess dance:

```python
class TestClassifyGhError:
    """Direct unit tests for _classify_gh_error."""

    @pytest.mark.parametrize("stderr", [
        "HTTP 404: Not Found (https://api.github.com/repos/derio-net/foo/issues)",
        "Could not resolve to a Repository with the name 'derio-net/foo'",
        "GraphQL: Could not resolve to a Repository with the name 'derio-net/foo'. (repository)",
        'Post "https://api.github.com/graphql": unexpected EOF',
        "read: connection reset by peer",
        "dial tcp: i/o timeout",
        "dial tcp: lookup api.github.com: no such host",
    ])
    def test_absent_or_transient_is_info(self, stderr):
        assert mod._classify_gh_error(stderr) == "info"

    @pytest.mark.parametrize("stderr", [
        "HTTP 401: Unauthorized",
        "HTTP 403: Forbidden",
        "HTTP 503: Service Unavailable",
        "HTTP 502: Bad Gateway",
        "unexpected JSON response",
        "",
    ])
    def test_real_errors_still_warn(self, stderr):
        assert mod._classify_gh_error(stderr) == "warn"
```

- [ ] **Step 2: Run the direct unit tests**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images/kali
python -m pytest tests/test_vk_issue_bridge.py::TestClassifyGhError -x -v 2>&1 | tail -20
```

Expected: 13 tests pass (7 info, 6 warn).

### Task 4: Smoke-check against real log sample

**Files:**
- None (verification step, no edits).

- [ ] **Step 1: Pull a sample of recent warn lines from the live pod**

This verifies the regex matches the actual stderr strings we observed, not just the synthesized test strings. From the Frank control host:

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- \
  bash -c 'grep "\[warn\]" ~/.willikins-agent/vk-bridge.log | tail -20'
```

Expected: 20 lines. Classify each mentally:
- `GraphQL: Could not resolve to a Repository` → should be info after fix
- `unexpected EOF` / `connection reset by peer` → should be info after fix
- `HTTP 5xx` → should stay warn
- Anything else → STOP and add to the classifier before merging

- [ ] **Step 2: Cross-check each sampled stderr against the classifier**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images/kali
python3 -c "
import sys
sys.path.insert(0, 'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('mod', 'scripts/vk-issue-bridge.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

samples = [
    'GraphQL: Could not resolve to a Repository with the name derio-net/derio-profile. (repository)',
    'Post \"https://api.github.com/graphql\": unexpected EOF',
    'HTTP 503: Service Unavailable',
]
for s in samples:
    print(f'{mod._classify_gh_error(s):5s}  {s[:80]}')
"
```

Expected:
```
info   GraphQL: Could not resolve to a Repository ...
info   Post \"https://api.github.com/graphql\": unexpected EOF
warn   HTTP 503: Service Unavailable
```

### Task 5: PR

**Files:**
- None (all code changes committed in Tasks 1–3; verification in Task 4).

- [ ] **Step 1: Commit on a feature branch**

```bash
cd /Users/derio/Docs/projects/DERIO_NET/agent-images
git checkout -b fix/vk-bridge-warn-patterns
git add kali/scripts/vk-issue-bridge.py kali/tests/test_vk_issue_bridge.py \
        docs/superpowers/plans/2026-04-22-vk-bridge-warn-patterns.md
git status
git commit -m "fix(bridge): broaden warn-demotion to GraphQL resolve + transient network"
```

- [ ] **Step 2: Open PR and reference the soak observation**

```bash
gh pr create --title "fix(bridge): broaden warn-demotion patterns (GraphQL + transient network)" \
  --body "$(cat <<'EOF'
## Summary

Extends the Phase 1 Task 4 warn-demotion fix from plan `2026-04-18-persistent-agent-reliability.md` to cover the error classes that were *actually* firing in production. Phase 3 T+48h soak observed 3121 warn lines, of which 2948 (~95%) were GraphQL-layer `Could not resolve to a Repository` for `derio-net/derio-profile` — the original regex only matched REST-layer 404s.

## What changed

- New module-level `_classify_gh_error(stderr) -> 'info' | 'warn'` helper with two pattern lists: `_ABSENT_REPO_PATTERNS` (repo-not-on-GitHub signals) and `_TRANSIENT_NETWORK_PATTERNS` (flakes the 2-min retry handles).
- `gh_list_ready_issues` now calls the helper instead of inline regex.
- 3 new integration tests in `TestDiscoveryWarningFiltering` (GraphQL resolve, EOF, connection reset), 1 regression guard (HTTP 5xx still warns), 13 direct-unit tests in new `TestClassifyGhError` class.

## Test plan

- [ ] `pytest tests/test_vk_issue_bridge.py::TestDiscoveryWarningFiltering -v` passes (5 tests)
- [ ] `pytest tests/test_vk_issue_bridge.py::TestClassifyGhError -v` passes (13 tests)
- [ ] `pytest tests/test_vk_issue_bridge.py -v` passes (full suite, no regressions)
- [ ] Smoke-check real log samples via the script in Plan Task 4 Step 2

## Observability after merge

- Expect \`vk-bridge.log\` warn rate to drop from ~65/h to <1/h (only 5xx/auth/unexpected-JSON).
- If warns return above ~5/h, the new "real" category needs classification — not a bug in this fix.

Refs: \`derio-net/agent-images#2\` (Phase 3 T+48h comment), plan \`docs/superpowers/plans/2026-04-22-vk-bridge-warn-patterns.md\`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: After merge, confirm observability in production**

Wait 1 hour post-deploy, then from the Frank control host:

```bash
source /Users/derio/Docs/projects/DERIO_NET/frank/.env && \
  kubectl exec -n secure-agent-pod deploy/secure-agent-pod -c kali -- \
  bash -c 'grep -c "\[warn\]" ~/.willikins-agent/vk-bridge.log'
```

Compare with the pre-fix baseline (3121 warns at T+48h). Expect new warns since deploy to be near-zero. If still accumulating, sample 10 fresh warn lines and open a follow-up PR to add the new category.

---

## Status updates

- 2026-04-22: Plan written. Drafted on the Frank control host during the Phase 3 T+48h checkpoint of the 2026-04-18 plan.
