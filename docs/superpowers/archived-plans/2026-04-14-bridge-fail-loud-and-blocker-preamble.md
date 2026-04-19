# Bridge Fail Loud And Blocker Preamble Implementation Plan

> **For VK agents:** Use vk-execute to implement assigned phases.
> **For local execution:** Use subagent-driven-development or executing-plans.
> **For dispatch:** Use vk-dispatch to create Issues from this plan.

**Spec:** `docs/superpowers/specs/2026-04-14-archive-and-unified-descriptions-design.md` (in derio-net/superpowers-for-vk)
**Status:** Not Started

**Goal:** Remove silent failure paths in `vk-issue-bridge.py` so parse/check errors fail loudly with actionable messages, and add a blocker-verification preamble to the workspace starting prompt so spawned agents refuse to duplicate upstream work.
**Architecture:** All changes live in `scripts/vk-issue-bridge.py`. This plan bootstraps a minimal `tests/test_vk_issue_bridge.py` harness. After merge, the cron-managed copy at `/opt/scripts/vk-issue-bridge.py` is redeployed in Phase 3.
**Tech Stack:** Python 3.11+, pytest

---

## Phase 0: Test bootstrap and fail-loud parse_dependencies [agentic]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/8 -->

### Task 1: Bootstrap test harness for the bridge

**Files:**
- Create: `tests/test_vk_issue_bridge.py`
- Create: `tests/__init__.py` (if missing)

- [ ] **Step 1: Confirm test layout**

```bash
ls tests/ 2>&1
```

If missing:

```bash
mkdir -p tests && touch tests/__init__.py
```

Verify pytest:

```bash
python -m pytest --version 2>&1
```

If missing, install via the project's normal path (e.g. `uv pip install pytest` or equivalent).

- [ ] **Step 2: Write initial import test**

Create `tests/test_vk_issue_bridge.py`:

```python
"""Tests for vk-issue-bridge.py fail-loud behavior."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

BRIDGE_PATH = Path(__file__).parent.parent / "scripts" / "vk-issue-bridge.py"


def _load_bridge():
    """Load vk-issue-bridge.py as a module named 'vk_issue_bridge'."""
    os.environ.setdefault("VK_ORG_ID", "test")
    os.environ.setdefault("VK_DERIO_OPS_PROJECT_ID", "test")
    spec = importlib.util.spec_from_file_location("vk_issue_bridge", BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["vk_issue_bridge"] = module
    spec.loader.exec_module(module)
    return module


def test_bridge_module_loads():
    mod = _load_bridge()
    assert hasattr(mod, "parse_dependencies")
    assert hasattr(mod, "check_blockers")
    assert hasattr(mod, "build_prompt")
```

Run: `python -m pytest tests/test_vk_issue_bridge.py -x 2>&1 | tail -10`. Expected: pass.

### Task 2: Fail loud when phase>0 has no parseable dependencies

**Files:**
- Modify: `scripts/vk-issue-bridge.py`
- Modify: `tests/test_vk_issue_bridge.py`

- [ ] **Step 1: Failing test — parse_dependencies gates on phase_number**

Append:

```python
class TestParseDependenciesFailLoud:
    def test_empty_deps_for_phase_zero_is_fine(self):
        mod = _load_bridge()
        assert mod.parse_dependencies(
            "## Dependencies\n\nNone — no blocking phases.\n",
            phase_number=0,
        ) == []

    def test_empty_deps_for_phase_n_raises(self):
        mod = _load_bridge()
        body = "## Dependencies\n\nSome prose without a dash-Blocked-by line.\n"
        with pytest.raises(ValueError, match="no parseable"):
            mod.parse_dependencies(body, phase_number=2)

    def test_missing_dependencies_section_for_phase_n_raises(self):
        mod = _load_bridge()
        with pytest.raises(ValueError, match="Dependencies"):
            mod.parse_dependencies("## Instruction\n\nDo stuff.\n", phase_number=1)

    def test_valid_dash_blocker_for_phase_n_parses(self):
        mod = _load_bridge()
        assert mod.parse_dependencies(
            "## Dependencies\n\n- Blocked by #42\n",
            phase_number=1,
        ) == [(None, 42)]
```

Run: expected TypeError (`parse_dependencies` takes one arg).

- [ ] **Step 2: Add phase_number parameter with fail-loud logic**

Replace `parse_dependencies` (scripts/vk-issue-bridge.py lines 169–192) with:

```python
def parse_dependencies(
    body: str,
    phase_number: int | None = None,
) -> list[tuple[str | None, int]]:
    """Extract issue references from the ## Dependencies section.

    Matches '- Blocked by #N' (same-repo) or '- Blocked by owner/repo#N' (cross-repo).

    Fail-loud: when ``phase_number`` is > 0 and no parseable dep line is found,
    raises ValueError. The bridge cannot gate work safely without parseable deps
    (see superpowers-for-vk spec 2026-04-14-archive-and-unified-descriptions-design.md).
    """
    deps: list[tuple[str | None, int]] = []
    in_deps = False
    saw_deps_section = False
    dep_re = re.compile(r"-\s+Blocked by (?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<num>\d+)")
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "## Dependencies":
            in_deps = True
            saw_deps_section = True
            continue
        if in_deps and (stripped.startswith("## ") or stripped == "---"):
            break
        if in_deps:
            m = dep_re.match(stripped)
            if m:
                deps.append((m.group("repo"), int(m.group("num"))))

    if phase_number is not None and phase_number > 0 and not deps:
        missing_section = "" if saw_deps_section else " No ## Dependencies section found."
        raise ValueError(
            f"Issue body for phase {phase_number} has no parseable "
            f"'- Blocked by #N' line in ## Dependencies.{missing_section} "
            f"Fix: run 'vk dispatch migrate <plan>' or re-dispatch. "
            f"The bridge cannot safely gate work without parseable deps."
        )
    return deps
```

Run the four tests; expect pass.

- [ ] **Step 3: Extend GhIssue with labels, update gh_list_ready_issues**

`GhIssue` (lines 73–83) does not carry labels. Add:

```python
@dataclass
class GhIssue:
    number: int
    title: str
    body: str
    html_url: str
    repo: str
    labels: tuple[str, ...] = ()

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]
```

In `gh_list_ready_issues` (lines 362–372) populate labels from gh JSON:

```python
issues.append(GhIssue(
    number=raw["number"],
    title=raw["title"],
    body=raw.get("body") or "",
    html_url=raw["url"],
    repo=repo,
    labels=tuple(l["name"] for l in raw.get("labels", [])),
))
```

Add a test:

```python
def test_ghissue_has_labels_default(self):
    mod = _load_bridge()
    i = mod.GhIssue(number=1, title="t", body="b",
                   html_url="u", repo="o/r")
    assert i.labels == ()
```

Run; expect pass.

- [ ] **Step 4: Thread phase_number into main() parse_dependencies call**

In `main()` (scripts/vk-issue-bridge.py around line 543), replace:

```python
deps = parse_dependencies(i.body)
```

with:

```python
phase_number: int | None = None
for lbl in i.labels:
    if lbl.startswith("phase:"):
        try:
            phase_number = int(lbl.split(":", 1)[1])
        except ValueError:
            pass
        break

try:
    deps = parse_dependencies(i.body, phase_number=phase_number)
except ValueError as exc:
    log(f"  x {i.repo}#{i.number}: PARSE ERROR — {exc}")
    push_failure_metric(str(i.number), "deps_parse_failed")
    failed += 1
    continue
```

Run `python -m pytest tests/ 2>&1 | tail -10`. Expected: pass.

---

## Phase 1: Fail-loud check_blockers [agentic]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/9 -->

### Task 1: Remove fail-open on gh errors

**Files:**
- Modify: `scripts/vk-issue-bridge.py`
- Modify: `tests/test_vk_issue_bridge.py`

- [ ] **Step 1: Failing tests — check_blockers raises on gh error**

Append:

```python
class TestCheckBlockersFailLoud:
    def test_check_blockers_raises_on_gh_error(self, monkeypatch):
        mod = _load_bridge()
        import subprocess
        def fake_run(*a, **kw):
            raise subprocess.CalledProcessError(1, "gh", stderr="auth required")
        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="unreachable"):
            mod.check_blockers("org/repo", [(None, 42)])

    def test_check_blockers_returns_open_list_on_success(self, monkeypatch):
        mod = _load_bridge()
        import subprocess, json
        class _R: stdout = json.dumps({"state": "OPEN"})
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _R())
        assert mod.check_blockers("org/repo", [(None, 42)]) == ["#42"]

    def test_check_blockers_skips_closed(self, monkeypatch):
        mod = _load_bridge()
        import subprocess, json
        class _R: stdout = json.dumps({"state": "CLOSED"})
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _R())
        assert mod.check_blockers("org/repo", [(None, 42)]) == []
```

Run; expect failure (current code fails open).

- [ ] **Step 2: Rewrite check_blockers fail-loud**

Replace lines 195–219 of `scripts/vk-issue-bridge.py`:

```python
def check_blockers(repo: str, deps: list[tuple[str | None, int]]) -> list[str]:
    """Return list of open blockers as human-readable strings.

    Fail-loud: any gh error or timeout raises RuntimeError. The previous
    fail-open behavior silently bypassed dependency gating when gh was
    misconfigured, which led to duplicate-work incidents.
    """
    open_blockers: list[str] = []
    for dep_repo, num in deps:
        check_repo = dep_repo if dep_repo else repo
        display = f"{dep_repo}#{num}" if dep_repo else f"#{num}"
        try:
            out = subprocess.run(
                ["gh", "issue", "view", str(num),
                 "--repo", check_repo, "--json", "state"],
                check=True, capture_output=True, text=True, timeout=10,
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError) as exc:
            raise RuntimeError(
                f"Blocker {display} in {check_repo} unreachable — cannot gate "
                f"safely. Fix: check gh auth, network, or that the Issue exists. "
                f"Underlying error: {exc}"
            ) from exc
        try:
            state = json.loads(out).get("state", "").upper()
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Blocker {display}: gh returned non-JSON. Output: {out[:200]!r}"
            ) from exc
        if state != "CLOSED":
            open_blockers.append(display)
    return open_blockers
```

Run tests; expect pass.

- [ ] **Step 3: Handle RuntimeError at call site**

In `main()` around line 545:

```python
if deps:
    try:
        open_blockers = check_blockers(i.repo, deps)
    except RuntimeError as exc:
        log(f"  x {i.repo}#{i.number}: BLOCKER CHECK FAILED — {exc}")
        push_failure_metric(str(i.number), "blocker_check_failed")
        failed += 1
        continue
    if open_blockers:
        blocker_str = ", ".join(open_blockers)
        log(f"  p {i.repo}#{i.number}: blocked by {blocker_str}")
        deferred += 1
        continue
```

Run full suite; expect pass.

---

## Phase 2: Blocker preamble in build_prompt [agentic]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/10 -->

### Task 1: Prepend preamble when deps present

**Files:**
- Modify: `scripts/vk-issue-bridge.py`
- Modify: `tests/test_vk_issue_bridge.py`

- [ ] **Step 1: Failing tests — preamble presence contract**

Append:

```python
class TestBuildPromptBlockerPreamble:
    def _issue(self, mod):
        return mod.GhIssue(
            number=77, title="Phase 2", body="body",
            html_url="https://gh/org/r/issues/77", repo="org/r",
            labels=(),
        )

    def _parsed(self, mod):
        return mod.ParsedBody(skill="vk-execute", repos=["r"], raw_instruction="x")

    def test_no_preamble_when_no_deps(self):
        mod = _load_bridge()
        p = mod.build_prompt(self._issue(mod), self._parsed(mod), deps=[])
        assert "BEFORE YOU BEGIN" not in p

    def test_preamble_when_deps_present(self):
        mod = _load_bridge()
        deps = [(None, 42), ("other/repo", 7)]
        p = mod.build_prompt(self._issue(mod), self._parsed(mod), deps=deps)
        assert "BEFORE YOU BEGIN" in p
        assert "#42" in p
        assert "other/repo#7" in p
        assert "STOP" in p
        assert "do not duplicate" in p.lower()
```

Run; expect TypeError.

- [ ] **Step 2: Extend build_prompt signature**

Replace lines 378–388:

```python
def build_prompt(
    issue: GhIssue,
    parsed: ParsedBody,
    deps: list[tuple[str | None, int]] | None = None,
) -> str:
    preamble = ""
    if deps:
        dep_refs = ", ".join(
            f"{r}#{n}" if r else f"#{n}" for r, n in deps
        )
        preamble = (
            f"BEFORE YOU BEGIN: This Issue declares dependencies: {dep_refs}.\n"
            f"Verify each is CLOSED via "
            f"`gh issue view <n> --repo <owner/repo> --json state`.\n"
            f"If any is OPEN:\n"
            f"  - STOP. Do not start work.\n"
            f"  - Do not duplicate the upstream work.\n"
            f"  - Do not start 'parts that don't depend on it'.\n"
            f"  - Exit with message: 'Blocked on <open_blocker>, not starting.'\n"
            f"The bridge should have deferred this workspace if a blocker were "
            f"open — if you see this and blockers are open, report it to the "
            f"operator.\n\n"
            f"---\n\n"
        )
    return (
        preamble
        + f"You are a VK-spawned agent working on GitHub Issue gh#{issue.number}:\n"
        f"{issue.title}\n\n"
        f"The Issue is at: {issue.html_url}\n"
        f"Repo: {parsed.repos[0]}\n\n"
        f"Use superpowers-for-vk:{parsed.skill} to implement this task.\n\n"
        "The full task description is in the GitHub Issue body — read it before "
        "starting. When you finish, open a PR. The lifecycle board will reflect "
        "your progress automatically."
    )
```

Run; expect pass.

- [ ] **Step 3: Thread deps into sync_issue call**

Update `sync_issue` signature (line 391):

```python
def sync_issue(
    issue: GhIssue,
    parsed: ParsedBody,
    deps: list[tuple[str | None, int]],
    client: VkMcpClient,
) -> bool:
```

Update its `build_prompt` call (line 455) to pass `deps=deps`.

In `main()` (around line 579), change:

```python
if sync_issue(i, parsed, client):
```

to:

```python
if sync_issue(i, parsed, deps, client):
```

Note: blocked Issues are already deferred earlier in the loop, so in practice `deps` here describes deps whose blockers are all CLOSED. The preamble still runs as defense-in-depth — if the bridge misfires or a human manually labels an Issue, the agent refuses.

Run full suite `python -m pytest tests/ 2>&1 | tail -10`. Expect pass.

---

## Phase 3: Deploy bridge to production [manual]
<!-- Tracking: https://github.com/derio-net/secure-agent-kali/issues/11 -->

### Task 1: Review, merge, deploy

- [ ] **Step 1: Create PR and merge**

Open a PR with the changes from Phases 0–2. Get review. Merge to main. No regressions for phase-0 Issues (no deps → no preamble, existing sync flow unchanged).

- [ ] **Step 2: Deploy updated script**

Follow the existing deployment path for `vk-issue-bridge.py`. Depending on infrastructure:

```bash
# Direct copy (if pod mounts source dir):
cp /home/claude/repos/secure-agent-kali/scripts/vk-issue-bridge.py /opt/scripts/vk-issue-bridge.py
chmod +x /opt/scripts/vk-issue-bridge.py
```

Or trigger the image rebuild + pod restart via whatever pipeline is standard.

- [ ] **Step 3: Smoke test next cron tick**

Wait ≤ 2 minutes:

```bash
ssh secure-agent-pod 'tail -40 /var/log/supercronic/vk-issue-bridge.log'
```

Expected: `[bridge] starting — dry_run=False` and a clean run. If Python traceback appears, roll back immediately by restoring the previous `/opt/scripts/vk-issue-bridge.py`.

- [ ] **Step 4: Verify deferral behavior on a live blocked Issue**

Find an Issue with a `phase:N` label where `N > 0` and whose `- Blocked by #M` blocker (`#M`) is still OPEN. In the next bridge tick, confirm the log shows:

```
  p derio-net/<repo>#<N>: blocked by #<M>
```

If instead the bridge spawned a workspace for it, ordering or label propagation is broken — investigate before proceeding.

- [ ] **Step 5: Notify superpowers-for-vk Phase 5 to proceed**

Once smoke test passes, the operational migration (Phase 5 of the superpowers-for-vk plan) can run. Leave a comment on the corresponding Phase 5 tracking Issue confirming bridge deployment. Mark this plan's Status as `Complete`.
