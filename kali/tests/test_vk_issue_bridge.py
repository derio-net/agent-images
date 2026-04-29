"""Unit tests for vk-issue-bridge — parser + helpers, no I/O."""
import importlib.util
import json as _json
import os
import subprocess as _subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Make the script importable as a module
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location(
    "vk_issue_bridge", SCRIPT_DIR / "vk-issue-bridge.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Use VkMcpError from the bridge module's namespace so class identity matches
# at exception-handling time (separate importlib loads create distinct classes)
VkMcpError = mod.VkMcpError

discover_repos = mod.discover_repos
parse = mod.parse_issue_body
parse_deps = mod.parse_dependencies
poll_pr_status = mod.poll_pr_status
GhIssue = mod.GhIssue
ParsedBody = mod.ParsedBody
sync_issue = mod.sync_issue


# --- discover_repos tests ---

def test_discover_repos_finds_git_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "repo-a", ".git"))
        os.makedirs(os.path.join(tmp, "repo-b", ".git"))
        os.makedirs(os.path.join(tmp, "not-a-repo"))  # no .git
        Path(os.path.join(tmp, "a-file.txt")).touch()  # plain file
        result = discover_repos(tmp)
        assert result == ["repo-a", "repo-b"]


def test_discover_repos_returns_sorted():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "zebra", ".git"))
        os.makedirs(os.path.join(tmp, "alpha", ".git"))
        os.makedirs(os.path.join(tmp, "middle", ".git"))
        result = discover_repos(tmp)
        assert result == ["alpha", "middle", "zebra"]


def test_discover_repos_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        result = discover_repos(tmp)
        assert result == []


def test_discover_repos_missing_dir():
    result = discover_repos("/nonexistent/path/that/does/not/exist")
    assert result == []


def test_discover_repos_permission_error():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "locked"))
        os.chmod(os.path.join(tmp, "locked"), 0o000)
        result = discover_repos(os.path.join(tmp, "locked"))
        os.chmod(os.path.join(tmp, "locked"), 0o755)  # restore for cleanup
        assert result == []


# --- Fixtures: real Issue body shapes from M5 smoke test ---

REAL_BODY = """Part of: Test Plan for Dispatcher Verification
Plan file: `docs/superpowers/plans/test-dispatcher-verification.md`
Task 1 of 3

---

## Instruction

Use superpowers:executing-plans to implement this task.

## Workspace

Repos: willikins

---

- [ ] **Step 1: Do nothing**

This is a test step.
"""

MULTI_REPO_BODY = """Part of: Cross-repo plan
Plan file: `docs/foo.md`
Task 2 of 4

---

## Instruction

Use superpowers:systematic-debugging to investigate the alert routing failure.

## Workspace

Repos: frank, willikins

---

Body content here.
"""

MISSING_INSTRUCTION_BODY = """Part of: Bad plan

---

## Workspace

Repos: willikins

---
"""

MISSING_REPOS_BODY = """## Instruction

Use superpowers:executing-plans to implement this task.

## Workspace

Some other text but no Repos line.
"""


def test_parses_real_dispatcher_body():
    p = parse(REAL_BODY)
    assert p.parse_error is None
    assert p.skill == "executing-plans"
    assert p.repos == ["willikins"]


def test_parses_multi_repo():
    p = parse(MULTI_REPO_BODY)
    assert p.parse_error is None
    assert p.skill == "systematic-debugging"
    assert p.repos == ["frank", "willikins"]


def test_missing_instruction_is_error():
    p = parse(MISSING_INSTRUCTION_BODY)
    assert p.parse_error is not None
    assert "Instruction" in p.parse_error


def test_missing_repos_is_error():
    p = parse(MISSING_REPOS_BODY)
    assert p.parse_error is not None
    assert "Workspace" in p.parse_error or "Repos" in p.parse_error


def test_empty_body_is_error():
    p = parse("")
    assert p.parse_error is not None


# --- Fixtures for sync/main tests ---

CONTENT_FACTORY_BODY = """Part of: Content Pipeline Foundation
Plan file: `docs/superpowers/plans/2026-03-29-content-pipeline-foundation.md`
Task 1 of 13

---

## Instruction

Use superpowers:executing-plans to implement this task.

## Workspace

Repos: content-factory

---

- [ ] **Step 1: Create the GitHub repo**
"""


def _make_issue(number=42, title="Task 1: Create Repository"):
    return GhIssue(
        number=number,
        title=title,
        body=CONTENT_FACTORY_BODY,
        html_url=f"https://github.com/derio-net/content-factory/issues/{number}",
        repo="derio-net/content-factory",
    )


def _make_parsed(repos=None):
    return ParsedBody(
        skill="executing-plans",
        repos=repos or ["content-factory"],
        raw_instruction="Use superpowers:executing-plans to implement this task.",
    )


def _make_mock_client():
    """Return a MagicMock configured as a VkMcpClient with sensible defaults.

    Response shapes match the real VK MCP server (tested 2026-04-10):
    - create_issue → {"issue_id": "..."}
    - get_issue → {"issue": {"id": ..., "simple_id": ..., ...}}
    - list_repos → {"repos": [...], "count": N}
    - start_workspace → {"id": "..."} (assumed, defensive extraction)
    """
    client = MagicMock()
    # create_issue returns {"issue_id": "..."} — NOT {"id": "..."}
    client.create_issue.return_value = {"issue_id": "card-uuid"}
    # get_issue wraps in {"issue": {...}}
    client.get_issue.return_value = {"issue": {"id": "card-uuid", "simple_id": "YIA-99"}}
    # update_issue succeeds
    client.update_issue.return_value = {}
    # list_repos returns {"repos": [...], "count": N}
    client.list_repos.return_value = {"repos": [
        {"id": "repo-uuid", "name": "content-factory"},
        {"id": "repo-uuid-2", "name": "willikins"},
    ], "count": 2}
    # start_workspace returns workspace dict
    client.start_workspace.return_value = {"id": "ws-uuid"}
    # link_workspace_issue succeeds
    client.link_workspace_issue.return_value = {}
    # list_issues returns empty for dedup
    client.list_issues.return_value = {"issues": []}
    # list_workspaces returns empty
    client.list_workspaces.return_value = {"workspaces": []}
    return client


# --- Sync tests: sync_issue creates card + workspace via MCP ---

@patch("subprocess.run")
def test_sync_creates_card_via_mcp(mock_run):
    """sync_issue should create card + workspace via MCP client."""
    issue = _make_issue(number=99, title="New task")
    parsed = _make_parsed()
    client = _make_mock_client()
    mock_run.return_value = MagicMock(returncode=0)

    result = sync_issue(issue, parsed, [], client)

    assert result is True
    # Card created via MCP
    client.create_issue.assert_called_once()
    # Workspace started via MCP
    client.start_workspace.assert_called_once()
    # Workspace linked to card via MCP
    client.link_workspace_issue.assert_called_once_with("ws-uuid", "card-uuid")


@patch("subprocess.run")
def test_sync_returns_true_even_when_label_fails(mock_run):
    """sync_issue must return True after workspace creation even if labelling fails.

    This is the bug that broke concurrency: label failure returned False,
    so the slot counter never decremented, and ALL issues got workspaces.
    """
    issue = _make_issue(number=7, title="Task 7")
    parsed = _make_parsed()
    client = _make_mock_client()

    # gh issue edit (label add) fails, gh issue view (lifecycle) succeeds
    import subprocess as sp
    def run_side_effect(args, **kwargs):
        if "edit" in args and "--add-label" in args:
            raise sp.CalledProcessError(1, args, stderr=b"'vk-synced' not found")
        return MagicMock(returncode=0, stdout='{}')

    mock_run.side_effect = run_side_effect

    result = sync_issue(issue, parsed, [], client)

    # Must return True — workspace IS running regardless of label failure
    assert result is True
    # MCP client used for card, workspace, link
    client.create_issue.assert_called_once()
    client.start_workspace.assert_called_once()
    client.link_workspace_issue.assert_called_once()


# --- Concurrency limit tests: main() defers when slots exhausted ---

@patch.object(mod, "push_heartbeat")
@patch.object(mod, "gh_list_ready_issues")
@patch.object(mod, "sync_issue")
def test_main_defers_when_no_slots(mock_sync, mock_issues, mock_hb):
    """When active workspaces >= MAX_CONCURRENT, new issues are deferred."""
    mock_client = _make_mock_client()
    mock_client.list_workspaces.return_value = {
        "workspaces": [{"id": f"ws-{i}", "worktree_deleted": False} for i in range(5)]
    }
    mock_client.list_issues.return_value = {"issues": []}

    issue = _make_issue()
    mock_issues.return_value = [issue]

    orig = mod.MAX_CONCURRENT
    mod.MAX_CONCURRENT = 3
    try:
        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            mod.main()
    finally:
        mod.MAX_CONCURRENT = orig

    # sync_issue should NOT have been called — issue deferred
    mock_sync.assert_not_called()


@patch.object(mod, "push_heartbeat")
@patch.object(mod, "gh_list_ready_issues")
@patch.object(mod, "sync_issue")
def test_main_processes_up_to_max_concurrent(mock_sync, mock_issues, mock_hb):
    """With 1 active workspace and max=3, should process at most 2 new issues."""
    mock_client = _make_mock_client()
    mock_client.list_workspaces.return_value = {
        "workspaces": [{"id": "ws-1", "worktree_deleted": False}]
    }
    mock_client.list_issues.return_value = {"issues": []}

    issues = [_make_issue(number=i, title=f"Task {i}") for i in range(1, 6)]
    mock_issues.return_value = issues
    mock_sync.return_value = True  # All syncs succeed

    orig = mod.MAX_CONCURRENT
    mod.MAX_CONCURRENT = 3
    try:
        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            mod.main()
    finally:
        mod.MAX_CONCURRENT = orig

    # Should have synced exactly 2 (3 max - 1 active = 2 slots)
    assert mock_sync.call_count == 2


@patch.object(mod, "push_heartbeat")
@patch.object(mod, "gh_list_ready_issues")
def test_main_allows_dedup_syncs_beyond_limit(mock_issues, mock_hb):
    """Dedup-only syncs (card exists) don't consume workspace slots."""
    mock_client = _make_mock_client()
    mock_client.list_workspaces.return_value = {
        "workspaces": [{"id": f"ws-{i}", "worktree_deleted": False} for i in range(3)]
    }

    # All 3 issues have existing cards (dedup case)
    issues = [_make_issue(number=i, title=f"Task {i}") for i in range(1, 4)]
    mock_client.list_issues.return_value = {
        "issues": [{"title": f"gh#{i}: Task {i}"} for i in range(1, 4)]
    }
    mock_issues.return_value = issues

    orig = mod.MAX_CONCURRENT
    mod.MAX_CONCURRENT = 3
    try:
        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                mod.main()
    finally:
        mod.MAX_CONCURRENT = orig

    # No sync_issue calls needed — dedup handled in main()
    # But all 3 should be counted as synced (label applied via subprocess)


# --- Slot accounting tests: sync_issue runs for real, label may fail ---

@patch.object(mod, "push_heartbeat")
@patch.object(mod, "check_blockers")
@patch.object(mod, "gh_list_ready_issues")
def test_main_respects_slots_even_when_label_fails(mock_issues, mock_blockers, mock_hb):
    """End-to-end: with label failure, slots must still decrement so
    concurrency limit is enforced.
    """
    mock_client = _make_mock_client()
    mock_client.list_workspaces.return_value = {"workspaces": []}
    mock_client.list_issues.return_value = {"issues": []}
    mock_blockers.return_value = []

    issues = [_make_issue(number=i, title=f"Task {i}") for i in range(1, 6)]
    mock_issues.return_value = issues

    # Patch sync_issue to simulate "workspace created but label failed" —
    # it should return True (the fix), consuming a slot
    with patch.object(mod, "sync_issue", return_value=True) as mock_sync:
        orig = mod.MAX_CONCURRENT
        mod.MAX_CONCURRENT = 3
        try:
            with patch.object(mod, "VkMcpClient", return_value=mock_client):
                mod.main()
        finally:
            mod.MAX_CONCURRENT = orig

        # Only 3 should be synced (3 slots available)
        assert mock_sync.call_count == 3


# --- Silent-failure metric tests: main() must push failure_total
#     on parse_error and unknown_repo paths so degradations are observable ---

@patch.object(mod, "push_heartbeat")
@patch.object(mod, "push_failure_metric")
@patch.object(mod, "gh_list_ready_issues")
def test_main_pushes_metric_on_parse_error(mock_issues, mock_failure, mock_hb):
    """An issue with a free-form body (no Instruction/Workspace blocks) must
    push willikins_vk_bridge_failure_total{reason='parse_error'}.

    Regression: 2026-04-29 incident where superpowers-for-vk#55 caused the
    bridge to exit 1 every 2 minutes without any metric ever incrementing,
    leaving the existing failure-rate alert blind.
    """
    mock_client = _make_mock_client()
    issue = _make_issue(number=55, title="Workflow gap notes")
    issue.body = "Two related cross-repo workflow gaps surfaced..."
    mock_issues.return_value = [issue]

    with patch.object(mod, "VkMcpClient", return_value=mock_client):
        mod.main()

    mock_failure.assert_called_once_with("55", "parse_error")


@patch.object(mod, "push_heartbeat")
@patch.object(mod, "push_failure_metric")
@patch.object(mod, "gh_list_ready_issues")
def test_main_pushes_metric_on_unknown_repo(mock_issues, mock_failure, mock_hb):
    """An issue whose ## Workspace points at a repo VK doesn't know about
    must push willikins_vk_bridge_failure_total{reason='unknown_repo'}.
    """
    mock_client = _make_mock_client()
    issue = _make_issue(number=77, title="Task in mystery repo")
    issue.body = (
        "## Instruction\n\n"
        "Use superpowers:executing-plans to implement this task.\n\n"
        "## Workspace\n\n"
        "Repos: not-a-real-repo\n"
    )
    mock_issues.return_value = [issue]

    with patch.object(mod, "VkMcpClient", return_value=mock_client):
        mod.main()

    mock_failure.assert_called_once_with("77", "unknown_repo")


# --- Dependency parser tests ---

BODY_WITH_DEPS = """Part of: Content Pipeline Foundation
Plan file: `plan.md`
Task 10 of 13

---

## Instruction

Use superpowers:executing-plans to implement this task.

## Workspace

Repos: content-factory

## Dependencies

- Blocked by #8
- Blocked by #9

---

Task body here.
"""

BODY_WITHOUT_DEPS = """## Instruction

Use superpowers:executing-plans to implement this task.

## Workspace

Repos: content-factory

---
"""

BODY_WITH_MALFORMED_DEPS = """## Dependencies

- Blocked by #8
- This is not a dependency line
- Blocked by number-not-a-number
- Blocked by #12
Random text

## Next Section
"""


def test_parse_dependencies_extracts_issue_numbers():
    deps = parse_deps(BODY_WITH_DEPS)
    assert deps == [(None, 8), (None, 9)]


def test_parse_dependencies_returns_empty_without_section():
    deps = parse_deps(BODY_WITHOUT_DEPS)
    assert deps == []


def test_parse_dependencies_ignores_malformed_lines():
    deps = parse_deps(BODY_WITH_MALFORMED_DEPS)
    assert deps == [(None, 8), (None, 12)]


def test_parse_dependencies_stops_at_section_boundary():
    body = """## Dependencies

- Blocked by #5

## Workspace

- Blocked by #99
"""
    deps = parse_deps(body)
    assert deps == [(None, 5)]


def test_parse_dependencies_stops_at_hr():
    body = """## Dependencies

- Blocked by #3

---

- Blocked by #99
"""
    deps = parse_deps(body)
    assert deps == [(None, 3)]


def test_parse_dependencies_empty_section():
    body = """## Dependencies

## Next
"""
    deps = parse_deps(body)
    assert deps == []


def test_parse_dependencies_accepts_cross_repo_form():
    """Supports ``- Blocked by owner/repo#N`` in addition to bare ``#N``.

    Regression: vk-dispatch manual dispatches emitted the cross-repo form
    even for same-repo dependencies, which the bridge silently ignored,
    causing both phases to run in parallel instead of sequentially.
    """
    body = """## Dependencies

- Blocked by derio-net/superpowers-for-vk#1
- Blocked by #2
- Blocked by other-org/other-repo#42
"""
    deps = parse_deps(body)
    assert deps == [
        ("derio-net/superpowers-for-vk", 1),
        (None, 2),
        ("other-org/other-repo", 42),
    ]


# --- Dependency gating integration tests ---

@patch.object(mod, "push_heartbeat")
@patch.object(mod, "check_blockers")
@patch.object(mod, "gh_list_ready_issues")
@patch.object(mod, "sync_issue")
def test_main_defers_when_blockers_open(mock_sync, mock_issues, mock_blockers, mock_hb):
    """Issues with open blockers are deferred."""
    mock_client = _make_mock_client()
    mock_client.list_workspaces.return_value = {"workspaces": []}
    mock_client.list_issues.return_value = {"issues": []}

    mock_blockers.return_value = ["#8"]  # blocker #8 still open

    issue = _make_issue(number=10, title="Task 10")
    issue.body = BODY_WITH_DEPS
    mock_issues.return_value = [issue]

    orig = mod.MAX_CONCURRENT
    mod.MAX_CONCURRENT = 3
    try:
        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            mod.main()
    finally:
        mod.MAX_CONCURRENT = orig

    mock_sync.assert_not_called()


@patch.object(mod, "push_heartbeat")
@patch.object(mod, "check_blockers")
@patch.object(mod, "gh_list_ready_issues")
@patch.object(mod, "sync_issue")
def test_main_proceeds_when_blockers_closed(mock_sync, mock_issues, mock_blockers, mock_hb):
    """Issues whose blockers are all closed proceed normally."""
    mock_client = _make_mock_client()
    mock_client.list_workspaces.return_value = {"workspaces": []}
    mock_client.list_issues.return_value = {"issues": []}

    mock_blockers.return_value = []  # all blockers closed

    issue = _make_issue(number=10, title="Task 10")
    issue.body = BODY_WITH_DEPS
    mock_issues.return_value = [issue]
    mock_sync.return_value = True

    orig = mod.MAX_CONCURRENT
    mod.MAX_CONCURRENT = 3
    try:
        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            mod.main()
    finally:
        mod.MAX_CONCURRENT = orig

    assert mock_sync.call_count == 1


# --- PR-status polling tests ---

def test_poll_transitions_to_in_review_on_open_pr():
    client = MagicMock()
    # list_issues is called twice: once for "In progress", once for "In review"
    def _list_issues(project_id, status=None, **kw):
        if status == "In progress":
            return {"issues": [{
                "id": "card-1", "simple_id": "YIA-50", "status": "In progress",
                "latest_pr_url": "https://github.com/derio-net/willikins/pull/42",
                "latest_pr_status": "open",
            }]}
        return {"issues": []}
    client.list_issues.side_effect = _list_issues
    client.update_issue.return_value = {"issue": {"status": "In review"}}
    poll_pr_status(client)
    client.update_issue.assert_called_once_with("card-1", status="In review")


def test_poll_transitions_to_done_on_merged_pr():
    client = MagicMock()
    def _list_issues(project_id, status=None, **kw):
        if status == "In review":
            return {"issues": [{
                "id": "card-2", "simple_id": "YIA-51", "status": "In review",
                "latest_pr_url": "https://github.com/derio-net/willikins/pull/43",
                "latest_pr_status": "merged",
            }]}
        return {"issues": []}
    client.list_issues.side_effect = _list_issues
    client.update_issue.return_value = {"issue": {"status": "Done"}}
    poll_pr_status(client)
    client.update_issue.assert_called_once_with("card-2", status="Done")


def test_poll_no_change_when_no_pr():
    client = MagicMock()
    client.list_issues.return_value = {
        "issues": [{
            "id": "card-3", "simple_id": "YIA-52", "status": "In progress",
            "latest_pr_url": None, "latest_pr_status": None,
        }]
    }
    poll_pr_status(client)
    client.update_issue.assert_not_called()


def test_poll_no_change_when_already_done():
    client = MagicMock()
    client.list_issues.return_value = {"issues": []}
    poll_pr_status(client)
    client.update_issue.assert_not_called()


def test_poll_handles_mcp_error_gracefully():
    client = MagicMock()
    client.list_issues.side_effect = VkMcpError("connection failed")
    poll_pr_status(client)  # should not raise
    client.update_issue.assert_not_called()


# --- Archive-on-merge + GH-issue-close-on-merge tests ---


def _done_card(
    *,
    card_id="card-X",
    simple_id="YIA-60",
    title="gh#42: Task 42",
    pr_url="https://github.com/derio-net/willikins/pull/99",
):
    """Fixture: a card currently 'In review' with a merged PR (→ will go Done)."""
    return {
        "id": card_id,
        "simple_id": simple_id,
        "status": "In review",
        "title": title,
        "latest_pr_url": pr_url,
        "latest_pr_status": "merged",
    }


def _make_poll_client(done_cards=None, workspaces=None):
    """Build a mock client where 'In review' returns the given cards."""
    client = MagicMock()

    def _list_issues(project_id, status=None, **kw):
        if status == "In review":
            return {"issues": done_cards or []}
        return {"issues": []}

    client.list_issues.side_effect = _list_issues
    client.list_workspaces.return_value = {"workspaces": workspaces or []}
    client.update_issue.return_value = {}
    client.update_workspace.return_value = {}
    return client


class TestPollArchivesWorkspaceOnMerge:
    def test_merged_pr_archives_matching_workspace(self, monkeypatch):
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
        client = _make_poll_client(
            done_cards=[_done_card(simple_id="YIA-60")],
            workspaces=[
                {"id": "ws-match", "name": "YIA-60 -> gh#42", "archived": False},
                {"id": "ws-other", "name": "YIA-61 -> gh#43", "archived": False},
            ],
        )
        poll_pr_status(client)
        # Card moved to Done
        client.update_issue.assert_called_with("card-X", status="Done")
        # Exactly one workspace archived — the matching one
        client.update_workspace.assert_called_once_with("ws-match", archived=True)

    def test_in_review_transition_does_not_archive(self, monkeypatch):
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
        client = MagicMock()

        def _list_issues(project_id, status=None, **kw):
            if status == "In progress":
                return {"issues": [{
                    "id": "c1", "simple_id": "YIA-70",
                    "status": "In progress",
                    "title": "gh#50: x",
                    "latest_pr_url": "https://github.com/derio-net/willikins/pull/77",
                    "latest_pr_status": "open",
                }]}
            return {"issues": []}

        client.list_issues.side_effect = _list_issues
        client.list_workspaces.return_value = {"workspaces": [
            {"id": "ws-x", "name": "YIA-70 -> gh#50", "archived": False},
        ]}
        client.update_issue.return_value = {}
        poll_pr_status(client)
        client.update_issue.assert_called_with("c1", status="In review")
        client.update_workspace.assert_not_called()

    def test_archive_failure_is_non_fatal(self, monkeypatch):
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
        client = _make_poll_client(
            done_cards=[_done_card(simple_id="YIA-62")],
            workspaces=[{"id": "ws-match", "name": "YIA-62 -> gh#44"}],
        )
        client.update_workspace.side_effect = VkMcpError("server down")
        poll_pr_status(client)  # must not raise
        client.update_issue.assert_called_with("card-X", status="Done")

    def test_list_workspaces_failure_is_non_fatal(self, monkeypatch):
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
        client = _make_poll_client(done_cards=[_done_card()])
        client.list_workspaces.side_effect = VkMcpError("timeout")
        poll_pr_status(client)
        client.update_issue.assert_called_with("card-X", status="Done")
        client.update_workspace.assert_not_called()

    def test_no_archive_when_status_transition_fails(self, monkeypatch):
        """If the card's Done transition fails, don't archive the workspace —
        the work may still be in flight and the operator needs to see the card."""
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
        client = _make_poll_client(
            done_cards=[_done_card()],
            workspaces=[{"id": "ws-match", "name": "YIA-60 -> gh#42"}],
        )
        client.update_issue.side_effect = VkMcpError("status transition failed")
        poll_pr_status(client)
        client.update_workspace.assert_not_called()

    def test_archive_skipped_when_simple_id_missing(self, monkeypatch):
        """Card without a simple_id can't be matched to a workspace; don't guess."""
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
        card = _done_card()
        card["simple_id"] = "?"
        client = _make_poll_client(
            done_cards=[card],
            workspaces=[{"id": "ws-any", "name": "? -> gh#42"}],
        )
        poll_pr_status(client)
        client.update_workspace.assert_not_called()


class TestPollClosesGhIssueOnMerge:
    def test_merged_pr_closes_gh_issue(self, monkeypatch):
        calls = []

        def fake_run(args, **kw):
            calls.append(list(args))
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(_subprocess, "run", fake_run)
        client = _make_poll_client(done_cards=[_done_card()])
        poll_pr_status(client)
        # Exactly one `gh issue close 42 --repo derio-net/willikins`
        gh_close = [c for c in calls if c[:3] == ["gh", "issue", "close"]]
        assert len(gh_close) == 1, f"expected 1 gh close call, got: {calls}"
        args = gh_close[0]
        assert "42" in args
        assert "--repo" in args
        assert "derio-net/willikins" in args

    def test_no_close_without_pr_url(self, monkeypatch):
        calls = []
        monkeypatch.setattr(_subprocess, "run", lambda args, **kw: calls.append(list(args)) or MagicMock(returncode=0))
        card = _done_card()
        card["latest_pr_url"] = None
        card["latest_pr_status"] = "merged"
        # Without a pr_url we can't derive the repo; skip the close.
        client = _make_poll_client(done_cards=[card])
        poll_pr_status(client)
        gh_close = [c for c in calls if c[:3] == ["gh", "issue", "close"]]
        assert gh_close == []

    def test_no_close_without_title(self, monkeypatch):
        """Card with no title → no gh#N → no repo/issue-number to close."""
        calls = []
        monkeypatch.setattr(_subprocess, "run", lambda args, **kw: calls.append(list(args)) or MagicMock(returncode=0))
        card = _done_card()
        card["title"] = ""
        client = _make_poll_client(done_cards=[card])
        poll_pr_status(client)
        gh_close = [c for c in calls if c[:3] == ["gh", "issue", "close"]]
        assert gh_close == []

    def test_already_closed_is_silent(self, monkeypatch):
        """'already closed' stderr from gh must not raise or log as failure."""
        def fake_run(args, **kw):
            raise _subprocess.CalledProcessError(
                1, args, stderr="HTTP 422: Issue is already closed"
            )

        monkeypatch.setattr(_subprocess, "run", fake_run)
        client = _make_poll_client(done_cards=[_done_card()])
        poll_pr_status(client)  # no raise
        client.update_issue.assert_called_with("card-X", status="Done")

    def test_gh_close_non_fatal_on_other_errors(self, monkeypatch):
        def fake_run(args, **kw):
            raise _subprocess.CalledProcessError(
                1, args, stderr="some other failure"
            )

        monkeypatch.setattr(_subprocess, "run", fake_run)
        client = _make_poll_client(done_cards=[_done_card()])
        poll_pr_status(client)  # no raise — card transition already happened
        client.update_issue.assert_called_with("card-X", status="Done")


# --- Orphan workspace sweep (card missing or card Done) ---

reap_orphan_workspaces = mod.reap_orphan_workspaces


class TestReapOrphanWorkspaces:
    """Bridge-named workspaces (`<simple_id> -> gh#<n>`) whose VK card
    no longer exists, or whose card is already Done, must be archived —
    poll_pr_status can't do it because it fires on card transitions.
    This is the failure mode that left 7 hum workspaces stuck after
    someone deleted their cards out-of-band."""

    def _client(self, *, workspaces, cards):
        client = MagicMock()
        client.list_workspaces.return_value = {"workspaces": workspaces}
        client.list_issues.return_value = {"issues": cards}
        client.update_workspace.return_value = {}
        return client

    def test_card_missing_workspace_archived(self):
        """Name matches bridge pattern and no card with that simple_id
        exists → archive."""
        client = self._client(
            workspaces=[{
                "id": "ws-orphan", "name": "FFE-50 -> gh#92",
                "archived": False, "pinned": False,
            }],
            cards=[],
        )
        reap_orphan_workspaces(client)
        client.update_workspace.assert_called_once_with(
            "ws-orphan", archived=True
        )

    def test_card_done_workspace_archived(self):
        """Card exists but is in Done status → archive the stuck workspace."""
        client = self._client(
            workspaces=[{
                "id": "ws-done", "name": "FFE-51 -> gh#93",
                "archived": False, "pinned": False,
            }],
            cards=[{"simple_id": "FFE-51", "status": "Done"}],
        )
        reap_orphan_workspaces(client)
        client.update_workspace.assert_called_once_with(
            "ws-done", archived=True
        )

    def test_card_in_progress_not_archived(self):
        """Card still active → leave workspace alone."""
        client = self._client(
            workspaces=[{
                "id": "ws-live", "name": "FFE-52 -> gh#94",
                "archived": False, "pinned": False,
            }],
            cards=[{"simple_id": "FFE-52", "status": "In progress"}],
        )
        reap_orphan_workspaces(client)
        client.update_workspace.assert_not_called()

    def test_non_bridge_workspace_not_archived(self):
        """Workspace name doesn't match `<simple_id> -> gh#<n>` → user-created,
        don't touch."""
        client = self._client(
            workspaces=[{
                "id": "ws-user", "name": "Pull from origin, then use vk-plan",
                "archived": False, "pinned": False,
            }],
            cards=[],
        )
        reap_orphan_workspaces(client)
        client.update_workspace.assert_not_called()

    def test_pinned_workspace_not_archived(self):
        """Pinned workspaces are user-protected — never archive."""
        client = self._client(
            workspaces=[{
                "id": "ws-pinned", "name": "FFE-53 -> gh#95",
                "archived": False, "pinned": True,
            }],
            cards=[],
        )
        reap_orphan_workspaces(client)
        client.update_workspace.assert_not_called()

    def test_list_workspaces_failure_non_fatal(self):
        client = MagicMock()
        client.list_workspaces.side_effect = VkMcpError("timeout")
        reap_orphan_workspaces(client)  # no raise
        client.update_workspace.assert_not_called()

    def test_list_issues_failure_non_fatal(self):
        client = MagicMock()
        client.list_workspaces.return_value = {"workspaces": [{
            "id": "ws-x", "name": "FFE-54 -> gh#96",
            "archived": False, "pinned": False,
        }]}
        client.list_issues.side_effect = VkMcpError("timeout")
        reap_orphan_workspaces(client)  # no raise
        client.update_workspace.assert_not_called()

    def test_update_workspace_failure_non_fatal(self):
        client = self._client(
            workspaces=[
                {"id": "ws-a", "name": "FFE-55 -> gh#97", "archived": False, "pinned": False},
                {"id": "ws-b", "name": "FFE-56 -> gh#98", "archived": False, "pinned": False},
            ],
            cards=[],
        )
        client.update_workspace.side_effect = VkMcpError("nope")
        reap_orphan_workspaces(client)  # no raise
        # Both attempts made; first failure doesn't abort second
        assert client.update_workspace.call_count == 2

    def test_multiple_orphans_all_archived(self):
        """The 7-hum case: multiple bridge workspaces, no cards — all swept."""
        workspaces = [
            {"id": f"ws-{i}", "name": f"FFE-{50 + i} -> gh#{92 + i}",
             "archived": False, "pinned": False}
            for i in range(7)
        ]
        client = self._client(workspaces=workspaces, cards=[])
        reap_orphan_workspaces(client)
        assert client.update_workspace.call_count == 7
        archived_ids = {c.args[0] for c in client.update_workspace.call_args_list}
        assert archived_ids == {f"ws-{i}" for i in range(7)}


# --- Phase-based body tests (superpowers-for-vk: prefix) ---

PHASE_BODY = """## Instruction

Use superpowers-for-vk:vk-execute to implement Phase 1 of this plan.

Plan file: `docs/superpowers/plans/2026-04-10-content-pipeline.md`
Phase: 1 (Pipeline Implementation)
Scope: Only the tasks under `## Phase 1`. Do not touch other phases.

## Workspace

Repos: content-factory

## Dependencies

- Blocked by #1
"""


def test_parses_phase_based_body():
    p = parse(PHASE_BODY)
    assert p.parse_error is None
    assert p.skill == "vk-execute"
    assert p.repos == ["content-factory"]


def test_phase_body_extracts_plan_reference():
    p = parse(PHASE_BODY)
    assert "content-pipeline.md" in p.raw_instruction


# --- Org-prefixed repo name tests ---

ORG_PREFIX_BODY = """## Instruction

Use superpowers-for-vk:vk-execute to implement Phase 0 of this plan.

## Workspace

Repos: derio-net/content-factory

## Dependencies

None — this is the first phase.
"""

ORG_PREFIX_MULTI_BODY = """## Instruction

Use superpowers:executing-plans to implement this task.

## Workspace

Repos: derio-net/content-factory, derio-net/willikins
"""


def test_strips_org_prefix_from_single_repo():
    p = parse(ORG_PREFIX_BODY)
    assert p.parse_error is None
    assert p.repos == ["content-factory"]


def test_strips_org_prefix_from_multi_repos():
    p = parse(ORG_PREFIX_MULTI_BODY)
    assert p.parse_error is None
    assert p.repos == ["content-factory", "willikins"]


def test_bare_repo_names_unchanged():
    """Existing bare names still work after the prefix-strip change."""
    p = parse(REAL_BODY)
    assert p.repos == ["willikins"]


# --- Fail-loud parse_dependencies tests (Phase 0) ---

class TestParseDependenciesFailLoud:
    def test_empty_deps_for_phase_zero_is_fine(self):
        assert parse_deps(
            "## Dependencies\n\nNone — no blocking phases.\n",
            phase_number=0,
        ) == []

    def test_empty_deps_for_phase_n_raises(self):
        body = "## Dependencies\n\nSome prose without a dash-Blocked-by line.\n"
        with pytest.raises(ValueError, match="no parseable"):
            parse_deps(body, phase_number=2)

    def test_missing_dependencies_section_for_phase_n_raises(self):
        with pytest.raises(ValueError, match="Dependencies"):
            parse_deps("## Instruction\n\nDo stuff.\n", phase_number=1)

    def test_valid_dash_blocker_for_phase_n_parses(self):
        assert parse_deps(
            "## Dependencies\n\n- Blocked by #42\n",
            phase_number=1,
        ) == [(None, 42)]

    def test_none_marker_accepted_for_phase_1(self):
        """First-phase plans can be numbered phase:1 (not phase:0). The
        'None — no blocking phases' marker emitted by vk-dispatch must be
        accepted as an explicit 'no deps' declaration regardless of phase
        number — otherwise agent-images#6, #7 get stuck with PARSE ERROR.
        """
        assert parse_deps(
            "## Dependencies\n\nNone — no blocking phases.\n",
            phase_number=1,
        ) == []

    def test_none_marker_accepted_for_high_phase_number(self):
        assert parse_deps(
            "## Dependencies\n\nNone — no blocking phases.\n",
            phase_number=7,
        ) == []

    def test_none_marker_case_insensitive(self):
        assert parse_deps(
            "## Dependencies\n\nnone — no blocking phases.\n",
            phase_number=3,
        ) == []

    def test_unrecognized_prose_still_raises_for_phase_n(self):
        """Prose that is neither a recognized 'none' marker nor a
        '- Blocked by #N' bullet still fails loud — catches typos."""
        body = "## Dependencies\n\nSee sibling plan for constraints.\n"
        with pytest.raises(ValueError, match="no parseable"):
            parse_deps(body, phase_number=2)

    def test_ghissue_has_labels_default(self):
        i = GhIssue(number=1, title="t", body="b",
                     html_url="u", repo="o/r")
        assert i.labels == ()


# --- check_blockers fail-loud tests (Phase 1) ---


class TestCheckBlockersFailLoud:
    def test_check_blockers_raises_on_gh_error(self, monkeypatch):
        def fake_run(*a, **kw):
            raise _subprocess.CalledProcessError(1, "gh", stderr="auth required")
        monkeypatch.setattr(_subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="unreachable"):
            mod.check_blockers("org/repo", [(None, 42)])

    def test_check_blockers_returns_open_list_on_success(self, monkeypatch):
        class _R:
            stdout = _json.dumps({"state": "OPEN"})
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: _R())
        assert mod.check_blockers("org/repo", [(None, 42)]) == ["#42"]

    def test_check_blockers_skips_closed(self, monkeypatch):
        class _R:
            stdout = _json.dumps({"state": "CLOSED"})
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: _R())
        assert mod.check_blockers("org/repo", [(None, 42)]) == []

    def test_check_blockers_raises_on_non_json_response(self, monkeypatch):
        class _R:
            stdout = "not json at all"
        monkeypatch.setattr(_subprocess, "run", lambda *a, **kw: _R())
        with pytest.raises(RuntimeError, match="non-JSON"):
            mod.check_blockers("org/repo", [(None, 42)])


# --- check_blockers integration test: RuntimeError in main() ---

BODY_WITH_SINGLE_DEP = """## Instruction

Use superpowers:executing-plans to implement this task.

## Workspace

Repos: content-factory

## Dependencies

- Blocked by #8

---
"""


@patch.object(mod, "push_heartbeat")
@patch.object(mod, "gh_list_ready_issues")
def test_main_counts_blocker_check_failure(mock_issues, mock_hb):
    """When check_blockers raises RuntimeError, main() increments failed
    and does not call sync_issue."""
    mock_client = _make_mock_client()
    mock_client.list_workspaces.return_value = {"workspaces": []}
    mock_client.list_issues.return_value = {"issues": []}

    issue = _make_issue(number=20, title="Task 20")
    issue.body = BODY_WITH_SINGLE_DEP
    mock_issues.return_value = [issue]

    with patch.object(mod, "check_blockers", side_effect=RuntimeError("gh auth broke")), \
         patch.object(mod, "sync_issue") as mock_sync, \
         patch.object(mod, "VkMcpClient", return_value=mock_client):
        orig = mod.MAX_CONCURRENT
        mod.MAX_CONCURRENT = 3
        try:
            mod.main()
        finally:
            mod.MAX_CONCURRENT = orig

    # sync_issue must NOT be called — issue was skipped due to blocker check failure
    mock_sync.assert_not_called()


# --- Blocker preamble in build_prompt tests (Phase 2) ---

build_prompt = mod.build_prompt


class TestBuildPromptBlockerPreamble:
    def _issue(self):
        return GhIssue(
            number=77, title="Phase 2", body="body",
            html_url="https://gh/org/r/issues/77", repo="org/r",
            labels=(),
        )

    def _parsed(self):
        return ParsedBody(skill="vk-execute", repos=["r"], raw_instruction="x")

    def test_no_preamble_when_no_deps(self):
        p = build_prompt(self._issue(), self._parsed(), deps=[])
        assert "BEFORE YOU BEGIN" not in p

    def test_preamble_when_deps_present(self):
        deps = [(None, 42), ("other/repo", 7)]
        p = build_prompt(self._issue(), self._parsed(), deps=deps)
        assert "BEFORE YOU BEGIN" in p
        assert "#42" in p
        assert "other/repo#7" in p
        assert "STOP" in p
        assert "do not duplicate" in p.lower()


class TestDiscoveryWarningFiltering:
    """Phase 1: 404s from local-only mirrors should not surface as warnings."""

    def test_gh_404_is_info_not_warn(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "discover_repos", lambda *a, **kw: ["derio-profile"])

        def fake_run(*args, **kwargs):
            raise _subprocess.CalledProcessError(
                1, "gh",
                stderr="HTTP 404: Not Found (https://api.github.com/repos/derio-net/derio-profile/issues)",
            )
        monkeypatch.setattr(_subprocess, "run", fake_run)

        issues = mod.gh_list_ready_issues()
        assert issues == []

        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "[warn]" not in combined
        assert "[info]" in combined
        assert "derio-profile" in combined

    def test_gh_generic_error_still_warns(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "discover_repos", lambda *a, **kw: ["willikins"])

        def fake_run(*args, **kwargs):
            raise _subprocess.CalledProcessError(
                1, "gh", stderr="HTTP 500: Internal Server Error",
            )
        monkeypatch.setattr(_subprocess, "run", fake_run)

        issues = mod.gh_list_ready_issues()
        assert issues == []

        captured = capsys.readouterr()
        combined = captured.err + captured.out
        assert "[warn]" in combined
        assert "willikins" in combined

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


# --- Multi-blocker check_blockers tests (parallel-dispatch-dag regression) ---
#
# Pins the bridge's AND-of-all-CLOSED contract for multi-blocker issues. The
# fan-in scenario in the spec ``2026-04-20-parallel-dispatch-dag-design.md``
# §5 depends on this behaviour: a downstream phase Issue with multiple
# ``- Blocked by #N`` lines must remain deferred until EVERY referenced
# Issue is CLOSED. The existing implementation at
# ``kali/scripts/vk-issue-bridge.py:210-242`` already iterates the list and
# fails loud on gh errors — these tests are regression coverage, not new
# behaviour, and are expected to pass as-is.

class TestCheckBlockersMultiDep:
    """Pin the fan-in contract: AND-of-all-CLOSED across multiple blockers."""

    @staticmethod
    def _fake_run_factory(states_by_number):
        """Build a subprocess.run replacement that returns per-issue state."""
        def fake_run(argv, *args, **kwargs):
            assert argv[:3] == ["gh", "issue", "view"], argv[:3]
            num = int(argv[3])
            result = MagicMock()
            result.returncode = 0
            result.stdout = _json.dumps({"state": states_by_number[num]})
            return result
        return fake_run

    def test_all_closed_returns_empty_list(self):
        deps = [(None, 1), (None, 2)]
        with patch.object(
            mod.subprocess,
            "run",
            side_effect=self._fake_run_factory({1: "CLOSED", 2: "CLOSED"}),
        ):
            assert mod.check_blockers("owner/repo", deps) == []

    def test_one_open_is_reported(self):
        deps = [(None, 1), (None, 2)]
        with patch.object(
            mod.subprocess,
            "run",
            side_effect=self._fake_run_factory({1: "OPEN", 2: "CLOSED"}),
        ):
            result = mod.check_blockers("owner/repo", deps)
        assert result == ["#1"]

    def test_both_open_reports_both(self):
        deps = [(None, 1), (None, 2)]
        with patch.object(
            mod.subprocess,
            "run",
            side_effect=self._fake_run_factory({1: "OPEN", 2: "OPEN"}),
        ):
            result = mod.check_blockers("owner/repo", deps)
        assert set(result) == {"#1", "#2"}

    def test_cross_repo_dep_uses_dep_repo_not_caller_repo(self):
        """A ``- Blocked by owner/other-repo#N`` line must gate against that
        other repo, not the current Issue's repo."""
        deps = [("other-owner/other-repo", 7)]
        calls = []

        def fake_run(argv, *args, **kwargs):
            calls.append(list(argv))
            result = MagicMock()
            result.returncode = 0
            result.stdout = _json.dumps({"state": "CLOSED"})
            return result

        with patch.object(mod.subprocess, "run", side_effect=fake_run):
            mod.check_blockers("default-owner/default-repo", deps)

        assert "--repo" in calls[0]
        repo_idx = calls[0].index("--repo") + 1
        assert calls[0][repo_idx] == "other-owner/other-repo"

    def test_gh_failure_raises_runtimeerror(self):
        """gh failure on any blocker must fail loud — the pre-hextra
        silent-bypass behaviour caused the very incident this DAG work is
        built on."""
        deps = [(None, 1)]

        def boom(argv, *args, **kwargs):
            raise _subprocess.CalledProcessError(1, argv, stderr="auth failed")

        with patch.object(mod.subprocess, "run", side_effect=boom):
            with pytest.raises(RuntimeError, match="unreachable"):
                mod.check_blockers("owner/repo", deps)


# --- Main-loop defer-before-slot-allocation tests ---
#
# Pins the ordering that prevents the Frank hextra workspace-slot inversion:
# blocked Issues must be deferred BEFORE the loop reaches the slot check or
# ``sync_issue`` call. Existing code already does this at
# ``kali/scripts/vk-issue-bridge.py:618-662``; these tests lock it down
# against future regressions.

_MULTI_BLOCKER_BODY = """Part of: Fan-in phase
Plan file: `docs/superpowers/plans/fan-in.md`

---

## Instruction

Use superpowers-for-vk:vk-execute to implement Phase 5 of this plan.

## Workspace

Repos: content-factory

## Dependencies

- Blocked by #101
- Blocked by #102
"""


def _make_multi_blocker_issue(number=300, title="Task 5: Fan-in phase"):
    return GhIssue(
        number=number,
        title=title,
        body=_MULTI_BLOCKER_BODY,
        html_url=f"https://github.com/derio-net/content-factory/issues/{number}",
        repo="derio-net/content-factory",
    )


class TestMainLoopDefersBlockedIssuesWithoutConsumingSlots:
    """The main loop must defer blocked Issues before consuming a slot.

    Frank hextra regression: under the old silent-bypass behaviour, blocked
    downstream phases consumed workspace slots while their upstream blockers
    remained queued — a priority inversion. With fail-loud blocker gating and
    the current ordering (parse → check_blockers → defer → slot check →
    sync_issue), a blocked Issue never reaches ``sync_issue`` and no slot is
    decremented.
    """

    @patch.object(mod, "push_heartbeat")
    @patch.object(mod, "gh_list_ready_issues")
    @patch.object(mod, "check_blockers")
    @patch.object(mod, "sync_issue")
    def test_blocked_issue_does_not_reach_sync_issue(
        self, mock_sync, mock_blockers, mock_issues, mock_hb
    ):
        mock_client = _make_mock_client()
        mock_client.list_workspaces.return_value = {"workspaces": []}
        mock_client.list_issues.return_value = {"issues": []}

        mock_issues.return_value = [_make_multi_blocker_issue()]
        mock_blockers.return_value = ["#101", "#102"]  # both still open

        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            mod.main()

        # The Issue must NOT have been synced — no workspace slot consumed.
        mock_sync.assert_not_called()

    @patch.object(mod, "push_heartbeat")
    @patch.object(mod, "gh_list_ready_issues")
    @patch.object(mod, "check_blockers")
    @patch.object(mod, "sync_issue")
    def test_unblocked_issue_reaches_sync_issue(
        self, mock_sync, mock_blockers, mock_issues, mock_hb
    ):
        mock_client = _make_mock_client()
        mock_client.list_workspaces.return_value = {"workspaces": []}
        mock_client.list_issues.return_value = {"issues": []}

        mock_issues.return_value = [_make_multi_blocker_issue()]
        mock_blockers.return_value = []  # all blockers now CLOSED
        mock_sync.return_value = True

        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            mod.main()

        mock_sync.assert_called_once()

    @patch.object(mod, "push_heartbeat")
    @patch.object(mod, "gh_list_ready_issues")
    @patch.object(mod, "check_blockers")
    @patch.object(mod, "sync_issue")
    def test_blocker_check_failure_defers_issue(
        self, mock_sync, mock_blockers, mock_issues, mock_hb
    ):
        """If check_blockers raises (gh auth failure, network error, etc.),
        the Issue must be failed/deferred — NOT silently treated as unblocked.
        """
        mock_client = _make_mock_client()
        mock_client.list_workspaces.return_value = {"workspaces": []}
        mock_client.list_issues.return_value = {"issues": []}

        mock_issues.return_value = [_make_multi_blocker_issue()]
        mock_blockers.side_effect = RuntimeError(
            "Blocker #101 in derio-net/content-factory unreachable — "
            "cannot gate safely."
        )

        with patch.object(mod, "VkMcpClient", return_value=mock_client):
            mod.main()

        # Issue must NOT have been synced even though check_blockers errored.
        mock_sync.assert_not_called()


if __name__ == "__main__":
    import sys as _sys
    failures = 0
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"  v {t.__name__}")
        except AssertionError as e:
            print(f"  x {t.__name__}: {e}")
            failures += 1
        except Exception as e:
            print(f"  x {t.__name__}: {type(e).__name__}: {e}")
            failures += 1
    print(f"{len(tests) - failures}/{len(tests)} passed")
    _sys.exit(1 if failures else 0)
