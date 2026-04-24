# Bridge Robustness Fixes Implementation Plan

> **For VK agents:** Use vk-execute to implement assigned phases.
> **For local execution:** Use subagent-driven-development or executing-plans.
> **For dispatch:** Use vk-dispatch to create Issues from this plan.

**Spec:** none (retroactive — no spec written)
**Status:** Complete

**Goal:** Close four robustness gaps in `kali/scripts/vk-issue-bridge.py` that were causing agent-images Issues #6 / #7 to fail pickup, seven hum workspaces (`FFE-50` … `FFE-56`) to permanently consume concurrency slots, and any future orphaned workspace to accumulate silently.
**Architecture:** All changes in the bridge script and its MCP client wrapper; tests extend the existing `kali/tests/test_vk_issue_bridge.py` harness. Changes are purely additive to `poll_pr_status` (Done-transition side effects) plus two new module-level helpers, and a single per-cycle sweep added to `main()`.
**Tech Stack:** Python 3.11+, pytest, VK MCP client.

---

## Phase 1: Accept explicit no-deps marker for any phase number [agentic]
**Depends on:** —

**Context:** `parse_dependencies` raises `ValueError` when `phase_number > 0` and there are no `- Blocked by #N` bullets. But `vk dispatch` emits the literal string `None — no blocking phases.` for phases with no predecessors, which was only accepted when `phase_number == 0`. Plans whose first phase is labelled `phase:1` (e.g. `vk-bridge-warn-patterns` single-phase plan; `vk-local-memory-profile` Phase 1/3) were stuck in the log forever with `PARSE ERROR`.

### Task 1: Widen the no-deps marker detection in `parse_dependencies`

**Files:**
- Modify: `kali/scripts/vk-issue-bridge.py` — `parse_dependencies`
- Modify: `kali/tests/test_vk_issue_bridge.py` — `TestParseDependenciesFailLoud`

- [x] **Step 1: TDD — add failing tests for the no-deps marker at any phase number**

Added four tests inside `TestParseDependenciesFailLoud`:

- `test_none_marker_accepted_for_phase_1`
- `test_none_marker_accepted_for_high_phase_number`
- `test_none_marker_case_insensitive`
- `test_unrecognized_prose_still_raises_for_phase_n` (regression guard — arbitrary prose must still fail loud)

Baseline: 3 new tests failed as expected, prose-regression passed.

- [x] **Step 2: Implement the marker regex**

In `parse_dependencies`:

```python
none_re = re.compile(r"^\s*none\b.*no blocking phases", re.IGNORECASE)
```

Track `saw_no_deps_marker` while scanning the `## Dependencies` section. Skip the fail-loud `raise` when the marker was seen. Existing `phase_number == 0` behaviour and the "prose without marker or bullets" error path are preserved.

- [x] **Step 3: Run the suite**

```bash
python3 -m pytest kali/tests/test_vk_issue_bridge.py -q
```

Expected: **61 passed** (4 new + 57 existing).

---

## Phase 2: Archive workspace + close GitHub Issue on Done transition [agentic]
**Depends on:** Phase 1

**Context:** `poll_pr_status` transitioned cards `In review → Done` when VK reported the PR merged, but never archived the linked workspace and never closed the GitHub Issue. Workspaces leaked — the 7 stuck `FFE-50`…`FFE-56` hum ones were all Done with merged PRs, still non-archived. GitHub Issue closure depended entirely on the agent remembering to put `Fixes #N` in the PR body.

### Task 1: Add `update_workspace` MCP client method

**Files:**
- Modify: `kali/scripts/vk_mcp_client.py`

- [x] **Step 1: Expose the MCP `update_workspace` tool**

```python
def update_workspace(self, workspace_id: str, **kwargs) -> Any:
    return self.call_tool("update_workspace", {
        "workspace_id": workspace_id, **kwargs
    })
```

Maps directly to the MCP tool (which PUTs `/api/workspaces/{id}` with `{archived, pinned, name}`). Verified against the Rust server: `crates/server/src/routes/workspaces/core.rs:83` fires `archive_workspace` when the `archived` field changes.

### Task 2: Wire Done transitions to archive workspace + close GH Issue

**Files:**
- Modify: `kali/scripts/vk-issue-bridge.py`
- Modify: `kali/tests/test_vk_issue_bridge.py`

- [x] **Step 1: TDD — `TestPollArchivesWorkspaceOnMerge`**

Six tests covering:
- Matching workspace archived on merge (name prefix `<simple_id> ->`)
- In-review transition does NOT archive (only Done)
- Archive failure non-fatal (card already transitioned)
- `list_workspaces` failure non-fatal
- No archive when card transition itself fails (don't archive state we don't understand)
- Missing `simple_id` skipped (can't be matched)

- [x] **Step 2: TDD — `TestPollClosesGhIssueOnMerge`**

Five tests covering:
- `gh issue close <N> --repo <owner/repo>` invoked once on merge
- No close without `latest_pr_url` (no repo to derive)
- No close without `gh#N:` in card title (no issue number to derive)
- `"already closed"` stderr is silent success
- Other `gh` errors are non-fatal

- [x] **Step 3: Implement `archive_workspace_for_card(client, simple_id)`**

Lists non-archived workspaces, matches by `name.startswith(f"{simple_id} ->")`, calls `client.update_workspace(ws_id, archived=True)`. All failure paths logged and swallowed — the card has already moved to Done.

- [x] **Step 4: Implement `close_gh_issue_for_card(title, pr_url)`**

Two small regexes:
```python
_GH_REPO_FROM_URL_RE = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/\d+")
_GH_ISSUE_NUM_FROM_TITLE_RE = re.compile(r"gh#(\d+)")
```

Invokes `gh issue close <num> --repo <repo>`. `"already closed"` detected via `stderr.lower()`; other errors log-and-continue.

- [x] **Step 5: Wire both into `poll_pr_status`**

After `update_issue(card_id, status="Done")` succeeds (only on Done, not In review):

```python
if new_status == "Done":
    archive_workspace_for_card(client, simple_id)
    close_gh_issue_for_card(title, pr_url)
```

- [x] **Step 6: Run the suite**

```bash
python3 -m pytest kali/tests/test_vk_issue_bridge.py -q
```

Expected: **72 passed** (11 new + 61 from Phase 1).

---

## Phase 3: Reap orphan workspaces each cycle [agentic]
**Depends on:** Phase 2

**Context:** During live verification, discovered the 7 stuck hum workspaces had their *cards deleted out-of-band* — the VK project had only 1 card left (`FFE-57`). Since `poll_pr_status` fires on card transitions and these cards no longer exist, neither Phase 2's archive hook nor any future Done-transition will touch them. A per-cycle sweep is needed that catches:
1. Workspaces whose card is gone entirely
2. Workspaces whose card is already Done but the workspace never got archived

### Task 1: Add `reap_orphan_workspaces` helper

**Files:**
- Modify: `kali/scripts/vk-issue-bridge.py`
- Modify: `kali/tests/test_vk_issue_bridge.py`

- [x] **Step 1: TDD — `TestReapOrphanWorkspaces`**

Nine tests covering:
- Card missing → archive
- Card present + status Done → archive
- Card present + status In progress → do NOT archive
- Workspace name not matching bridge pattern → do NOT archive (user-created)
- Pinned workspace → never archive
- `list_workspaces` failure non-fatal
- `list_issues` failure non-fatal
- `update_workspace` failure on one orphan does not abort sweep of the next
- Multiple orphans (the 7-hum case) all archived

- [x] **Step 2: Implement `reap_orphan_workspaces(client)`**

Named-workspace regex: `r"^(?P<sid>\S+)\s*->\s*gh#\d+\s*$"` — only workspaces that were created by the bridge itself are candidates; anything else (user-created, vk-plan spawned, etc.) is left alone.

Indexes cards into `{simple_id: status}`; archives when `card_status.get(sid) is None` (missing) or `== "Done"`.

- [x] **Step 3: Call once per bridge cycle in `main()`**

Added after `poll_pr_status(client)`:

```python
log("[bridge] reaping orphan workspaces...")
reap_orphan_workspaces(client)
```

- [x] **Step 4: Run the full suite**

```bash
python3 -m pytest kali/tests/ -q
```

Expected: **97 passed** (9 new + 88 from Phases 1-2 and unrelated tests in the same directory).

---

## Phase 4: Commit [manual]
**Depends on:** Phase 3

- [x] **Step 1: Commit all four fixes together**

```bash
git add kali/scripts/vk-issue-bridge.py kali/scripts/vk_mcp_client.py kali/tests/test_vk_issue_bridge.py
git commit
```

Landed as `64a6fb6` — `fix(bridge): archive on merge, close GH issue, reap orphans, accept no-deps marker`.

---

## Deployment (outside plan scope)

The bridge runs from `/opt/scripts/vk-issue-bridge.py` inside the `secure-agent-pod`, baked into the `agent-images` container image. Ship path:

1. Push `main` → GH Actions builds a new `agent-images` image.
2. Bump the pod image tag in `frank/apps/secure-agent-pod/` via the frank bumper PR.
3. Within ≤ 2 minutes of pod rollout, the next bridge cycle logs:
   - `[bridge] reaping orphan workspaces...`
   - Seven `↙ FFE-5X: reaped workspace XXXXXXXX (no card)` lines
   - Bridge picks up `agent-images#6` and `#7` (parse error gone).
