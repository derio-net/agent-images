"""Tests for the additive `vk.bridge` integration in vk-issue-bridge.py.

Covers:
  - `_McpAdapter` — the protocol shim feeding `vk.bridge.tick` against the
    existing `VkMcpClient`; its `create_card` must replicate the legacy
    `sync_issue` pipeline (create_issue → set status → list_repos →
    start_workspace → link_workspace_issue).
  - `discover_plans` + `tick` integration — plan-driven path produces the
    expected (title, body, issue_url) call on the adapter and toggles
    `vk-synced` on the linked Issue.
  - Delineation — v2-plan Issues are NOT re-processed by the legacy
    per-Issue loop; non-v2 Issues still flow through the legacy loop.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location(
    "vk_issue_bridge", SCRIPT_DIR / "vk-issue-bridge.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

VkMcpError = mod.VkMcpError
_McpAdapter = mod._McpAdapter
_parse_issue_url = mod._parse_issue_url


# ---------- shared fixtures ----------

V2_BODY = textwrap.dedent(
    """\
    📦 Repo:   derio-net/agent-images
    📋 Plan:   docs/superpowers/plans/2026-05-12-bridge-vk-library-integration
    🎯 Phase:  1/3 — Refactor

    ## Instruction

    Use superpowers-for-vk:vk-execute to implement this task.

    ## Workspace

    Repos: derio-net/agent-images

    ## Dependencies

    None — no blocking phases.
    """
)


def _make_mock_inner():
    """MagicMock matching VkMcpClient's response shapes (per legacy fixtures)."""
    inner = MagicMock()
    inner.create_issue.return_value = {"issue_id": "card-uuid", "simple_id": "AGI-99"}
    inner.get_issue.return_value = {"issue": {"id": "card-uuid", "simple_id": "AGI-99"}}
    inner.update_issue.return_value = {}
    inner.list_repos.return_value = {
        "repos": [{"id": "repo-uuid", "name": "agent-images"}],
        "count": 1,
    }
    inner.start_workspace.return_value = {"id": "ws-uuid"}
    inner.link_workspace_issue.return_value = {}
    return inner


# ---------- _parse_issue_url ----------


def test_parse_issue_url_extracts_repo_and_number():
    assert _parse_issue_url(
        "https://github.com/derio-net/agent-images/issues/61"
    ) == ("derio-net/agent-images", 61)


def test_parse_issue_url_rejects_non_issue_url():
    with pytest.raises(ValueError):
        _parse_issue_url("https://github.com/derio-net/agent-images/pull/64")


# ---------- _McpAdapter.create_card pipeline ----------


def test_adapter_create_card_runs_full_pipeline_in_order():
    inner = _make_mock_inner()
    parent = MagicMock()  # records call order across methods
    parent.attach_mock(inner.create_issue, "create_issue")
    parent.attach_mock(inner.update_issue, "update_issue")
    parent.attach_mock(inner.list_repos, "list_repos")
    parent.attach_mock(inner.start_workspace, "start_workspace")
    parent.attach_mock(inner.link_workspace_issue, "link_workspace_issue")

    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    card_id = adapter.create_card(
        title="Phase 1: Refactor",
        body=V2_BODY,
        issue_url="https://github.com/derio-net/agent-images/issues/61",
    )

    assert card_id == "card-uuid"
    assert [c[0] for c in parent.mock_calls] == [
        "create_issue",
        "update_issue",
        "list_repos",
        "start_workspace",
        "link_workspace_issue",
    ]


def test_adapter_create_issue_uses_project_id_and_gh_prefix_title():
    inner = _make_mock_inner()
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    adapter.create_card(
        title="Refactor bridge",
        body=V2_BODY,
        issue_url="https://github.com/derio-net/agent-images/issues/61",
    )
    args, kwargs = inner.create_issue.call_args
    assert args[0] == "proj-uuid"
    assert args[1] == "gh#61: Refactor bridge"
    assert kwargs["description"] == "https://github.com/derio-net/agent-images/issues/61"


def test_adapter_update_issue_sets_in_progress_status():
    inner = _make_mock_inner()
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    adapter.create_card(
        title="Phase 1",
        body=V2_BODY,
        issue_url="https://github.com/derio-net/agent-images/issues/61",
    )
    inner.update_issue.assert_called_once_with("card-uuid", status="In progress")


def test_adapter_start_workspace_targets_resolved_repo_uuid_and_main_branch():
    inner = _make_mock_inner()
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    adapter.create_card(
        title="Phase 1",
        body=V2_BODY,
        issue_url="https://github.com/derio-net/agent-images/issues/61",
    )
    _, kwargs = inner.start_workspace.call_args
    assert kwargs["repositories"] == [{"repo_id": "repo-uuid", "branch": "main"}]
    assert kwargs["executor"] == "CLAUDE_CODE"
    assert kwargs["issue_id"] == "card-uuid"
    assert kwargs["name"] == "AGI-99 -> gh#61"
    assert "gh#61" in kwargs["prompt"]
    assert "superpowers-for-vk:vk-execute" in kwargs["prompt"]


def test_adapter_link_workspace_to_card():
    inner = _make_mock_inner()
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    adapter.create_card(
        title="Phase 1",
        body=V2_BODY,
        issue_url="https://github.com/derio-net/agent-images/issues/61",
    )
    inner.link_workspace_issue.assert_called_once_with("ws-uuid", "card-uuid")


def test_adapter_raises_when_body_lacks_instruction_or_workspace():
    inner = _make_mock_inner()
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    with pytest.raises(VkMcpError):
        adapter.create_card(
            title="Phase 1",
            body="no instructions here",
            issue_url="https://github.com/derio-net/agent-images/issues/61",
        )
    inner.create_issue.assert_not_called()


def test_adapter_raises_when_repo_not_in_vk():
    inner = _make_mock_inner()
    inner.list_repos.return_value = {"repos": [], "count": 0}
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    with pytest.raises(VkMcpError, match="not found"):
        adapter.create_card(
            title="Phase 1",
            body=V2_BODY,
            issue_url="https://github.com/derio-net/agent-images/issues/61",
        )
    inner.start_workspace.assert_not_called()


def test_adapter_raises_when_card_creation_returns_no_id():
    inner = _make_mock_inner()
    inner.create_issue.return_value = {"simple_id": "AGI-99"}  # missing id
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    with pytest.raises(VkMcpError, match="no id"):
        adapter.create_card(
            title="Phase 1",
            body=V2_BODY,
            issue_url="https://github.com/derio-net/agent-images/issues/61",
        )


def test_adapter_status_failure_does_not_block_workspace_creation():
    inner = _make_mock_inner()
    inner.update_issue.side_effect = VkMcpError("status transition unavailable")
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    card_id = adapter.create_card(
        title="Phase 1",
        body=V2_BODY,
        issue_url="https://github.com/derio-net/agent-images/issues/61",
    )
    assert card_id == "card-uuid"
    inner.start_workspace.assert_called_once()
    inner.link_workspace_issue.assert_called_once()


def test_adapter_link_failure_does_not_raise():
    inner = _make_mock_inner()
    inner.link_workspace_issue.side_effect = VkMcpError("link failed")
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    # Workspace IS running — must not raise; tick adds vk-synced.
    card_id = adapter.create_card(
        title="Phase 1",
        body=V2_BODY,
        issue_url="https://github.com/derio-net/agent-images/issues/61",
    )
    assert card_id == "card-uuid"


def test_adapter_update_card_delegates_to_inner_update_issue():
    inner = _make_mock_inner()
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")
    adapter.update_card(card_id="card-uuid", status="Done")
    inner.update_issue.assert_called_once_with("card-uuid", status="Done")


# ---------- discover_plans + tick (real vk.bridge against a fake gh) ----------


def _write_plan(plan_dir: Path, tracking_url: str | None) -> None:
    """Write the smallest v2 plan that vk.parser accepts."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "_meta.yaml").write_text(
        "schema_version: 2\n"
        "plan: fixture-plan\n"
        "spec: docs/superpowers/specs/fixture.md\n"
        "target_repo: derio-net/agent-images\n"
        "vk_version: '>=2.1.0,<3.0.0'\n"
        "created: '2026-05-12'\n"
    )
    tracking_line = (
        f"  tracking_issue: '{tracking_url}'" if tracking_url else
        "  tracking_issue: null"
    )
    (plan_dir / "01.yaml").write_text(
        "schema_version: 2\n"
        "phase:\n"
        "  number: 1\n"
        "  title: Fixture Phase\n"
        "  tag: agentic\n"
        "  depends_on: []\n"
        f"{tracking_line}\n"
        "tasks:\n"
        "- number: 1\n"
        "  title: Single task\n"
        "  steps:\n"
        "  - id: P1.T1.S1\n"
        "    text: |-\n"
        "      Do the thing\n"
        "state:\n"
        "  steps:\n"
        "    P1.T1.S1:\n"
        "      state: ' '\n"
        "      ticked_at: null\n"
        "      note: null\n"
        "  completion:\n"
        "    at: null\n"
        "    note: null\n"
        "    observed_prs: []\n"
    )


class _FakeGh:
    """Minimal GhClient implementing what discover_plans + tick + apply call."""

    def __init__(self, view_responses: dict[tuple[str, int], dict]):
        self._view = view_responses
        self.label_edits: list[tuple[str, int, frozenset, frozenset]] = []
        self.created_issues: list[dict] = []

    def view_issue(self, repo, number):
        return self._view.get((repo, number), {"state": "OPEN", "labels": []})

    def list_linked_prs(self, repo, issue_number):
        return []

    def edit_issue_labels(self, repo, number, *, add, remove):
        self.label_edits.append((repo, number, frozenset(add), frozenset(remove)))

    def edit_issue_state(self, repo, number, *, state, reason=None):
        pass

    def edit_issue_body(self, repo, number, body):
        pass

    def create_issue(self, repo, *, title, body, labels):
        self.created_issues.append(
            {"repo": repo, "title": title, "body": body, "labels": list(labels)}
        )
        return f"https://github.com/{repo}/issues/{100 + len(self.created_issues)}"

    def ensure_labels(self, repo, labels):
        pass


def test_discover_plans_returns_plan_with_vk_ready_phase(tmp_path, monkeypatch):
    from vk import bridge as vk_bridge

    repo_root = tmp_path / "agent-images"
    plan_dir = repo_root / "docs" / "superpowers" / "plans" / "fixture-plan"
    tracking_url = "https://github.com/derio-net/agent-images/issues/61"
    _write_plan(plan_dir, tracking_url)

    monkeypatch.setenv("VK_REPOS_DIR", str(tmp_path))
    fake_gh = _FakeGh({
        ("derio-net/agent-images", 61): {
            "state": "OPEN",
            "labels": ["vk-ready", "phase:1"],
        }
    })

    plans = vk_bridge.discover_plans("derio-net/agent-images", fake_gh)
    assert len(plans) == 1
    assert plans[0].phases[0].phase.tracking_issue == tracking_url


def test_discover_plans_skips_plans_without_vk_ready(tmp_path, monkeypatch):
    from vk import bridge as vk_bridge

    repo_root = tmp_path / "agent-images"
    plan_dir = repo_root / "docs" / "superpowers" / "plans" / "fixture-plan"
    _write_plan(
        plan_dir, "https://github.com/derio-net/agent-images/issues/61",
    )

    monkeypatch.setenv("VK_REPOS_DIR", str(tmp_path))
    fake_gh = _FakeGh({
        ("derio-net/agent-images", 61): {
            "state": "OPEN",
            "labels": ["vk-synced"],  # no vk-ready
        }
    })
    plans = vk_bridge.discover_plans("derio-net/agent-images", fake_gh)
    assert plans == []


def test_tick_invokes_adapter_create_card_with_title_body_and_url(tmp_path, monkeypatch):
    """End-to-end: vk.bridge.tick drives _McpAdapter.create_card with the
    expected (title, body, issue_url) and the renderer adds `vk-synced`
    to the Issue's labels via gh.edit_issue_labels."""
    from vk import bridge as vk_bridge

    repo_root = tmp_path / "agent-images"
    plan_dir = repo_root / "docs" / "superpowers" / "plans" / "fixture-plan"
    tracking_url = "https://github.com/derio-net/agent-images/issues/61"
    _write_plan(plan_dir, tracking_url)

    monkeypatch.setenv("VK_REPOS_DIR", str(tmp_path))
    fake_gh = _FakeGh({
        ("derio-net/agent-images", 61): {
            "state": "OPEN",
            "labels": ["vk-ready", "phase:1"],
        }
    })
    inner = _make_mock_inner()
    adapter = _McpAdapter(inner, project_id="proj-uuid", org_id="org-uuid")

    [plan] = vk_bridge.discover_plans("derio-net/agent-images", fake_gh)
    result = vk_bridge.tick(plan, fake_gh, adapter)

    assert result.errors == 0
    assert result.synced == 1
    # adapter saw exactly one create_card with the right URL.
    inner.create_issue.assert_called_once()
    create_args = inner.create_issue.call_args
    assert "gh#61:" in create_args[0][1]
    # tick added vk-synced via gh.edit_issue_labels
    synced_edits = [e for e in fake_gh.label_edits if "vk-synced" in e[2]]
    assert synced_edits, f"expected a vk-synced label add, got {fake_gh.label_edits}"


# ---------- main() delineation: v2 vs legacy ----------


@pytest.mark.no_stub_vk_bridge
def test_main_delineates_v2_plan_issues_from_legacy_path(monkeypatch):
    """Issues claimed by a v2 plan flow through vk.bridge.tick only; the
    legacy per-Issue loop's sync_issue is invoked for non-v2 Issues only."""
    monkeypatch.delenv("VK_BRIDGE_SKIP_LIB_PATH", raising=False)

    # Build a fake Plan that returns one phase whose tracking_issue is #61.
    fake_plan = MagicMock()
    fake_phase = MagicMock()
    fake_phase.phase.tracking_issue = "https://github.com/derio-net/agent-images/issues/61"
    fake_phase.phase.number = 1
    fake_plan.phases = [fake_phase]

    monkeypatch.setattr(mod, "_DISCOVER_PLANS", lambda repo, gh: (
        [fake_plan] if repo == "derio-net/agent-images" else []
    ))
    tick_calls = []
    monkeypatch.setattr(
        mod, "_TICK",
        lambda plan, gh, mcp: tick_calls.append(plan) or mod.vk_bridge.TickResult(
            synced=1, errors=0, skipped=0, failures=(),
        ),
    )
    monkeypatch.setattr(mod, "_REAL_GH_CLIENT", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "discover_repos", lambda *_a, **_kw: ["agent-images"])

    v2_issue = mod.GhIssue(
        number=61,
        title="Refactor",
        body="(unused — v2-owned)",
        html_url="https://github.com/derio-net/agent-images/issues/61",
        repo="derio-net/agent-images",
    )
    legacy_issue = mod.GhIssue(
        number=42,
        title="Legacy task",
        body=(
            "## Instruction\n\nUse superpowers:executing-plans to implement this task.\n\n"
            "## Workspace\n\nRepos: agent-images\n\n"
            "## Dependencies\n\nNone — no blocking phases.\n"
        ),
        html_url="https://github.com/derio-net/agent-images/issues/42",
        repo="derio-net/agent-images",
    )

    monkeypatch.setattr(mod, "gh_list_ready_issues", lambda: [v2_issue, legacy_issue])
    monkeypatch.setattr(mod, "push_heartbeat", lambda: None)
    monkeypatch.setattr(mod, "push_success_metric", lambda: None)
    monkeypatch.setattr(mod, "push_failure_metric", lambda *_a, **_kw: None)

    mock_client = MagicMock()
    mock_client.list_workspaces.return_value = {"workspaces": []}
    mock_client.list_issues.return_value = {"issues": []}
    mock_client.list_repos.return_value = {
        "repos": [{"id": "repo-uuid", "name": "agent-images"}], "count": 1,
    }
    sync_calls: list = []
    monkeypatch.setattr(
        mod, "sync_issue",
        lambda issue, parsed, deps, client: sync_calls.append(issue) or True,
    )
    monkeypatch.setattr(mod, "VkMcpClient", lambda *a, **kw: mock_client)
    monkeypatch.setattr(mod, "poll_pr_status", lambda *_a, **_kw: None)
    monkeypatch.setattr(mod, "reap_orphan_workspaces", lambda *_a, **_kw: None)

    rc = mod.main()

    assert rc == 0
    assert tick_calls == [fake_plan], "v2 plan must be ticked exactly once"
    assert [i.number for i in sync_calls] == [42], (
        "legacy sync_issue must be called for #42 only (not the v2-owned #61)"
    )


# ---------- cross-phase dependency rendering (v2.1.0 regression guard) ----------


def _copy_fixture_plan(tmp_path: Path, fixture_name: str) -> Path:
    """Copy a static plan fixture into a tmp checkout that VK_REPOS_DIR can scan."""
    src = Path(__file__).parent / "fixtures" / fixture_name
    dst = tmp_path / "agent-images" / "docs" / "superpowers" / "plans" / fixture_name
    shutil.copytree(src, dst)
    return dst


def test_bridge_dispatches_v2_plan_with_correct_issue_deps(tmp_path, monkeypatch):
    """End-to-end regression test for v2.1.0's renderer fix.

    Phase 1's tracking Issue (#99) exists and is `vk-ready`. Phase 2 has no
    tracking Issue yet — `tick` → `apply` must CREATE it, and the rendered
    body must reference Phase 1's tracking-Issue number (`- Blocked by #99`),
    NOT the raw phase number (`- Blocked by #1`). The latter was the v2.0.0
    bug that v2.1.0 fixed; this test pins the fix all the way through the
    bridge's library-delegation path.
    """
    from vk import bridge as vk_bridge

    _copy_fixture_plan(tmp_path, "two-phase-cross-dep")
    monkeypatch.setenv("VK_REPOS_DIR", str(tmp_path))

    fake_gh = _FakeGh({
        ("derio-net/agent-images", 99): {
            "state": "OPEN",
            "labels": ["vk-ready", "phase:1"],
        }
    })
    mock_mcp = MagicMock()
    mock_mcp.create_card.return_value = "card-uuid"

    [plan] = vk_bridge.discover_plans("derio-net/agent-images", fake_gh)
    assert [p.phase.number for p in plan.phases] == [1, 2]
    assert tuple(plan.phases[1].phase.depends_on) == (1,)
    assert plan.phases[1].phase.tracking_issue is None

    result = vk_bridge.tick(plan, fake_gh, mock_mcp)

    assert result.errors == 0, result.failures
    assert result.synced == 1, "Phase 1 (vk-ready) should sync to VK"

    phase2_creates = [
        c for c in fake_gh.created_issues if "Phase 2/2" in c["title"]
    ]
    assert len(phase2_creates) == 1, (
        f"expected exactly one create_issue for Phase 2, got "
        f"{[c['title'] for c in fake_gh.created_issues]}"
    )
    phase2_body = phase2_creates[0]["body"]
    assert "- Blocked by #99" in phase2_body, (
        f"Phase 2 body must reference Phase 1's tracking Issue number (#99), "
        f"got body:\n{phase2_body}"
    )
    assert "- Blocked by #1" not in phase2_body, (
        f"Renderer leaked phase number into dep ref (v2.0.0 bug regressed); "
        f"body:\n{phase2_body}"
    )
