# Parallel Dispatch DAG — Bridge Audit Implementation Plan

**Spec:** https://github.com/derio-net/superpowers-for-vk/blob/main/docs/superpowers/specs/2026-04-20-parallel-dispatch-dag-design.md
**Status:** Not Started

**Goal:** Pin the VK Issue Bridge's multi-blocker contract with regression tests: `check_blockers` gates on ALL-CLOSED (AND semantics) and the main loop defers a blocked Issue **before** consuming a workspace slot. The initial read-through confirms the existing code already upholds the contract, so this plan is primarily additive test coverage — no behavioural change expected.

**Architecture:** Two test additions in `kali/tests/test_vk_issue_bridge.py`. Task 1 adds a unit test for `check_blockers` that exercises the multi-blocker iteration + gh-state gating. Task 2 adds a main-loop integration test that confirms the ordering "check_blockers → defer → slot allocation" described at `kali/scripts/vk-issue-bridge.py:611-662`. No production code changes unless the tests surface a gap.

**Tech stack:** Python 3.11+, pytest ≥ 8. Existing harness in `kali/tests/` uses `importlib.util` to load the dash-named script; the new tests extend the same pattern.

---

## Phase 1: Bridge audit + fan-in regression test [agentic]

### Task 1: Multi-blocker unit test for `check_blockers`

**Files:**
- Modify: `kali/tests/test_vk_issue_bridge.py`

**Reference lines in the production code:**
- `parse_dependencies` — `kali/scripts/vk-issue-bridge.py:170-207`
- `check_blockers` — `kali/scripts/vk-issue-bridge.py:210-242`

These two functions together implement the bridge-side DAG gate. `parse_dependencies` iterates every `- Blocked by #N` line in the `## Dependencies` section. `check_blockers` iterates that list, calls `gh issue view --json state` per blocker, and returns the list of non-CLOSED display strings. Callers defer the Issue if the return list is non-empty (main loop at `kali/scripts/vk-issue-bridge.py:619-631`).

- [ ] **Step 1: Read the two functions and note the contract**

Open `kali/scripts/vk-issue-bridge.py` at line 170 and line 210. Confirm:

- `parse_dependencies` returns `list[tuple[str | None, int]]` — each element is `(repo | None, issue_number)`.
- `check_blockers` raises `RuntimeError` on any `gh` failure (fail-loud, no silent bypass).
- `check_blockers` returns a list of display strings like `#42` or `owner/repo#42`; empty list = all blockers CLOSED.

No code change. This step exists to ensure the executing agent understands the invariants before writing tests against them.

- [ ] **Step 2: Write failing regression tests for multi-blocker `check_blockers`**

Append to `kali/tests/test_vk_issue_bridge.py` in the "Dependency parser tests" section (around line 408, where `parse_deps` tests live):

```python
# --- Multi-blocker check_blockers tests (parallel-dispatch-dag regression) ---

class TestCheckBlockersMultiDep:
    """Pin the fan-in contract: AND-of-all-CLOSED across multiple blockers."""

    def _mock_gh_states(self, states_by_number: dict[int, str]):
        """Factory for subprocess.run replacement that returns state per issue number."""
        def fake_run(argv, *args, **kwargs):
            assert argv[:3] == ["gh", "issue", "view"]
            num = int(argv[3])
            result = MagicMock()
            result.returncode = 0
            result.stdout = _json.dumps({"state": states_by_number[num]})
            return result
        return fake_run

    def test_all_closed_returns_empty_list(self):
        check_blockers = mod.check_blockers
        deps = [(None, 1), (None, 2)]
        with patch.object(mod.subprocess, "run",
                          side_effect=self._mock_gh_states({1: "CLOSED", 2: "CLOSED"})):
            assert check_blockers("owner/repo", deps) == []

    def test_one_open_is_reported(self):
        check_blockers = mod.check_blockers
        deps = [(None, 1), (None, 2)]
        with patch.object(mod.subprocess, "run",
                          side_effect=self._mock_gh_states({1: "OPEN", 2: "CLOSED"})):
            result = check_blockers("owner/repo", deps)
        assert result == ["#1"]

    def test_both_open_reports_both(self):
        check_blockers = mod.check_blockers
        deps = [(None, 1), (None, 2)]
        with patch.object(mod.subprocess, "run",
                          side_effect=self._mock_gh_states({1: "OPEN", 2: "OPEN"})):
            result = check_blockers("owner/repo", deps)
        assert set(result) == {"#1", "#2"}

    def test_cross_repo_dep_uses_dep_repo(self):
        check_blockers = mod.check_blockers
        deps = [("other-owner/other-repo", 7)]
        calls: list[list[str]] = []

        def fake_run(argv, *args, **kwargs):
            calls.append(list(argv))
            result = MagicMock()
            result.returncode = 0
            result.stdout = _json.dumps({"state": "CLOSED"})
            return result

        with patch.object(mod.subprocess, "run", side_effect=fake_run):
            check_blockers("default-owner/default-repo", deps)

        # The gh call must target the dep's repo, not the caller's repo.
        assert "--repo" in calls[0]
        repo_idx = calls[0].index("--repo") + 1
        assert calls[0][repo_idx] == "other-owner/other-repo"

    def test_gh_failure_raises_runtimeerror(self):
        check_blockers = mod.check_blockers
        deps = [(None, 1)]

        def boom(argv, *args, **kwargs):
            raise _subprocess.CalledProcessError(1, argv, stderr="auth failed")

        with patch.object(mod.subprocess, "run", side_effect=boom):
            with pytest.raises(RuntimeError, match="unreachable — cannot gate safely"):
                check_blockers("owner/repo", deps)
```

- [ ] **Step 3: Run the tests to observe the result**

```
cd ~/Docs/projects/DERIO_NET/agent-images
uv run --with pytest pytest kali/tests/test_vk_issue_bridge.py::TestCheckBlockersMultiDep -v
```

Expected: **PASS** — the existing `check_blockers` implementation already iterates and gates correctly. If any test fails, treat the failure as a bug in the bridge and jump to Step 4.

- [ ] **Step 4 (conditional): Fix any gap surfaced by the tests**

Only execute this step if a test failed in Step 3. Read the failing assertion and the corresponding production code, then make the minimum change to `kali/scripts/vk-issue-bridge.py::check_blockers` that satisfies the contract. Re-run the tests until green.

If all tests pass in Step 3 as expected, **skip this step** — the contract is already upheld.

- [ ] **Step 5: Run the full bridge test suite to confirm no regressions**

```
cd ~/Docs/projects/DERIO_NET/agent-images
uv run --with pytest pytest kali/tests/test_vk_issue_bridge.py -q
```

Expected: PASS — existing tests continue to pass alongside the new ones.

- [ ] **Step 6: Commit**

```
git add kali/tests/test_vk_issue_bridge.py
git commit -m "test(bridge): pin multi-blocker check_blockers contract (parallel-dispatch-dag)"
```

### Task 2: Main-loop integration test — defer before slot allocation

**Files:**
- Modify: `kali/tests/test_vk_issue_bridge.py`

Reference lines in production code:
- Deferral before slot check: `kali/scripts/vk-issue-bridge.py:618-631`
- Slot availability check: `kali/scripts/vk-issue-bridge.py:655-658`
- `sync_issue` call (the work + slot decrement): `kali/scripts/vk-issue-bridge.py:660-662`

The correctness property: if `check_blockers` returns a non-empty list, the loop `continue`s without reaching `sync_issue`, so no workspace is created and no slot is decremented. This test pins that invariant.

- [ ] **Step 1: Write a failing integration test for the defer-before-slot ordering**

Append to `kali/tests/test_vk_issue_bridge.py` in the "Concurrency limit tests" section (around line 292, near `test_main_defers_when_no_slots`):

```python
class TestMainLoopDefersBlockedIssuesWithoutConsumingSlots:
    """Blocked Issues must not consume a workspace slot.

    Frank hextra regression: Phases 3-5 had consumed slots while Phases 1-2
    were still queued because the bridge treated unparseable deps as unblocked.
    Post-fix, deps are dash-prefixed and the bridge iterates + gates properly.
    This test confirms the end-to-end ordering: parse → check_blockers → (if
    blocked) defer → (only if unblocked) slot check → sync_issue.
    """

    @patch("vk_issue_bridge.push_heartbeat")
    @patch("vk_issue_bridge.find_open_issues")
    @patch("vk_issue_bridge.check_blockers")
    @patch("vk_issue_bridge.sync_issue")
    def test_blocked_issue_does_not_reach_sync_issue(
        self,
        mock_sync: MagicMock,
        mock_blockers: MagicMock,
        mock_issues: MagicMock,
        mock_hb: MagicMock,
    ) -> None:
        blocked = _make_issue(number=300, title="Task 5: Fan-in phase")
        blocked.body = (
            "## Instruction\n\nDo.\n\n## Workspace\n\nRepos: o/r\n\n"
            "## Dependencies\n\n- Blocked by #101\n- Blocked by #102\n"
        )
        mock_issues.return_value = [blocked]
        mock_blockers.return_value = ["#101", "#102"]  # both still open

        client = _make_mock_client()

        # Run a single bridge tick.
        exit_code = mod.main_once(client) if hasattr(mod, "main_once") else mod.main(client=client, once=True)  # type: ignore[arg-type]

        # The Issue must NOT have been synced — no slot consumed.
        mock_sync.assert_not_called()

    @patch("vk_issue_bridge.push_heartbeat")
    @patch("vk_issue_bridge.find_open_issues")
    @patch("vk_issue_bridge.check_blockers")
    @patch("vk_issue_bridge.sync_issue")
    def test_unblocked_issue_reaches_sync_issue(
        self,
        mock_sync: MagicMock,
        mock_blockers: MagicMock,
        mock_issues: MagicMock,
        mock_hb: MagicMock,
    ) -> None:
        unblocked = _make_issue(number=301, title="Task 6: Downstream")
        unblocked.body = (
            "## Instruction\n\nDo.\n\n## Workspace\n\nRepos: o/r\n\n"
            "## Dependencies\n\n- Blocked by #101\n"
        )
        mock_issues.return_value = [unblocked]
        mock_blockers.return_value = []  # all closed
        mock_sync.return_value = True

        client = _make_mock_client()
        exit_code = mod.main_once(client) if hasattr(mod, "main_once") else mod.main(client=client, once=True)  # type: ignore[arg-type]

        mock_sync.assert_called_once()
```

- [ ] **Step 2: Run the test to observe the result**

```
cd ~/Docs/projects/DERIO_NET/agent-images
uv run --with pytest pytest kali/tests/test_vk_issue_bridge.py::TestMainLoopDefersBlockedIssuesWithoutConsumingSlots -v
```

Three possible outcomes:

- **PASS:** The ordering holds. Proceed to Step 4.
- **FAIL with `AttributeError` on `main_once` or `main(once=...)`:** The existing bridge `main()` doesn't expose a single-tick entry point. Fall back to Step 3 to adapt the test to the existing shape of `main()`.
- **FAIL with `AssertionError: called_once()`:** The bridge is reaching `sync_issue` even with blockers open — this is the bug the user worried about and must be fixed in Step 4 (conditional).

- [ ] **Step 3 (conditional): Adapt the test to `main()`'s existing entry point**

Open `kali/scripts/vk-issue-bridge.py` and find the `main()` definition. Inspect how the existing tests at `kali/tests/test_vk_issue_bridge.py:297-349` invoke it (see `test_main_defers_when_no_slots`, `test_main_processes_up_to_max_concurrent`). Adapt the two new tests to use the same invocation pattern (e.g., directly calling `main()` with the mocked `client`, catching `SystemExit`, or whichever form the existing tests use).

Re-run Step 2 until the tests execute correctly.

- [ ] **Step 4 (conditional): Fix any ordering gap**

Only execute this step if Step 2 or 3 showed a genuine ordering bug (`sync_issue` called for a blocked Issue). Reorder the main loop in `kali/scripts/vk-issue-bridge.py` so that `check_blockers` and the deferral `continue` happen strictly before the slot check and the `sync_issue` call. Re-run until green.

If both tests passed as expected, **skip this step**.

- [ ] **Step 5: Run the full bridge test suite**

```
cd ~/Docs/projects/DERIO_NET/agent-images
uv run --with pytest pytest kali/tests/test_vk_issue_bridge.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```
git add kali/tests/test_vk_issue_bridge.py
git commit -m "test(bridge): pin defer-before-slot-allocation ordering for multi-blocker issues"
```

### Phase 1 exit

Run the full bridge test suite one more time as a sanity check before pushing:

```
cd ~/Docs/projects/DERIO_NET/agent-images
uv run --with pytest pytest kali/tests/test_vk_issue_bridge.py -q
```

If only tests changed (no production code change), push directly to `main` per operator approval. The commits serve as executable documentation of the bridge's multi-blocker contract.

If production code changed in Step 4 of either task, open a PR instead of pushing to main, and link the superpowers-for-vk spec and its Phase 2 PR in the description.
