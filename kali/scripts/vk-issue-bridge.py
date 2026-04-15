#!/usr/bin/env python3
"""vk-issue-bridge.py — Sync vk-ready GitHub Issues to VibeKanban.

Runs as a supercronic-invoked cron job every 2 minutes inside the
secure-agent-pod. Finds GitHub Issues labelled `vk-ready` that are not yet
labelled `vk-synced`, creates a corresponding VK kanban card and workspace
(linked), and labels the Issue `vk-synced` for idempotency.

Spec:    docs/superpowers/specs/2026-04-08-vk-issue-bridge-design.md
Addendum: docs/superpowers/specs/2026-04-08-vk-issue-bridge-spike-addendum.md
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vk_mcp_client import VkMcpClient, VkMcpError

# --- Config (env-overridable) ---
VK_ORG_ID            = os.environ["VK_ORG_ID"]
VK_DERIO_OPS_PROJECT = os.environ["VK_DERIO_OPS_PROJECT_ID"]
GH_LABEL_READY       = os.environ.get("VK_LABEL_READY", "vk-ready")
GH_LABEL_SYNCED      = os.environ.get("VK_LABEL_SYNCED", "vk-synced")
TRANSITION_SCRIPT    = os.environ.get(
    "WILLIKINS_TRANSITION_SCRIPT",
    "/home/claude/repos/willikins/scripts/hooks/vk-lifecycle-transition.sh",
)
PUSHGATEWAY_URL      = os.environ.get(
    "PUSHGATEWAY_URL",
    "http://pushgateway.monitoring.svc.cluster.local:9091",
)
DRY_RUN              = "--dry-run" in sys.argv
MAX_CONCURRENT       = int(os.environ.get("VK_MAX_CONCURRENT", "8"))

# Base directory for repo discovery (env-overridable)
REPOS_DIR = os.environ.get("VK_REPOS_DIR", "/home/claude/repos")


def discover_repos(repos_dir: str = REPOS_DIR) -> list[str]:
    """Scan repos_dir for first-level git repositories.

    Returns a sorted list of directory names that contain a .git subdirectory.
    """
    try:
        entries = os.scandir(repos_dir)
    except FileNotFoundError:
        log(f"[warn] repos dir not found: {repos_dir}")
        return []
    except PermissionError:
        log(f"[warn] repos dir not accessible: {repos_dir}")
        return []
    repos = []
    with entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=True) and os.path.isdir(
                os.path.join(entry.path, ".git")
            ):
                repos.append(entry.name)
    if not repos:
        log(f"[warn] no git repos found in {repos_dir}")
    return sorted(repos)


def log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class GhIssue:
    number: int
    title: str
    body: str
    html_url: str
    repo: str  # owner/repo
    labels: tuple[str, ...] = ()

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]


@dataclass
class ParsedBody:
    skill: str            # e.g. "executing-plans"
    repos: list[str]      # repo names (just names, not derio-net/...)
    raw_instruction: str
    parse_error: str | None = None


def parse_issue_body(body: str) -> ParsedBody:
    """Extract skill + repos from the structured Instruction/Workspace blocks.

    plan-dispatcher writes:

        ## Instruction

        Use superpowers:<skill> to implement this task.

        ## Workspace

        Repos: <comma-separated>

    Returns ParsedBody with parse_error set if either block is missing.
    """
    skill = None
    repos: list[str] = []
    raw_instruction = ""
    err_parts: list[str] = []

    lines = body.splitlines()
    in_instr = False
    in_wksp = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Instruction"):
            in_instr, in_wksp = True, False
            continue
        if stripped.startswith("## Workspace"):
            in_instr, in_wksp = False, True
            continue
        if stripped.startswith("## ") or stripped.startswith("---"):
            in_instr, in_wksp = False, False
            continue
        if in_instr and stripped:
            raw_instruction += stripped + " "
            for prefix in ("superpowers-for-vk:", "superpowers:"):
                if prefix in stripped:
                    idx = stripped.index(prefix) + len(prefix)
                    tail = stripped[idx:]
                    skill_name = ""
                    for ch in tail:
                        if ch.isalnum() or ch in "-_":
                            skill_name += ch
                        else:
                            break
                    if skill_name:
                        skill = skill_name
                    break
        if in_wksp and stripped.lower().startswith("repos:"):
            after = stripped.split(":", 1)[1]
            repos = [r.strip().split("/")[-1] for r in after.split(",") if r.strip()]

    if not skill or not repos:
        preview = body[:100].replace("\n", "\\n") if body else "<empty>"
        log(f"PARSE DEBUG — body preview: {preview}")
    if not skill:
        err_parts.append(
            "missing '## Instruction' section with 'superpowers-for-vk:<skill>' "
            "or 'superpowers:<skill>' — re-dispatch with latest vk CLI or edit issue body"
        )
    if not repos:
        err_parts.append(
            "missing '## Workspace' section with 'Repos: owner/repo' line "
            "— re-dispatch with latest vk CLI or edit issue body"
        )

    return ParsedBody(
        skill=skill or "executing-plans",
        repos=repos,
        raw_instruction=raw_instruction.strip(),
        parse_error="; ".join(err_parts) if err_parts else None,
    )


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


def check_blockers(repo: str, deps: list[tuple[str | None, int]]) -> list[str]:
    """Return list of open blockers as human-readable strings.

    For each (dep_repo, num) tuple, check the Issue state. Same-repo deps
    (dep_repo is None) are checked in ``repo``; cross-repo deps use their
    explicit repo. On any error (deleted issue, API failure), fail open —
    omit that dep from blockers.
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
            state = json.loads(out).get("state", "").upper()
            if state != "CLOSED":
                open_blockers.append(display)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                json.JSONDecodeError):
            log(f"  ! could not check blocker {display} in {check_repo} — treating as resolved")
    return open_blockers


# --- VK MCP helpers ---

def poll_pr_status(client: VkMcpClient) -> None:
    """Check in-progress/in-review VK cards for PR status changes.

    Transitions:
      - In progress + open PR → In review
      - In review + merged PR → Done
    """
    for status in ("In progress", "In review"):
        try:
            resp = client.list_issues(VK_DERIO_OPS_PROJECT, status=status)
        except VkMcpError as e:
            log(f"[warn] PR poll: could not list '{status}' cards: {e}")
            continue

        for card in resp.get("issues", []):
            card_id = card.get("id")
            simple_id = card.get("simple_id", "?")
            pr_status = card.get("latest_pr_status")
            current_status = card.get("status", "")

            if not pr_status:
                continue

            new_status = None
            if current_status == "In progress" and pr_status == "open":
                new_status = "In review"
            elif current_status == "In review" and pr_status == "merged":
                new_status = "Done"

            if new_status:
                try:
                    client.update_issue(card_id, status=new_status)
                    log(f"  ↗ {simple_id}: {current_status} → {new_status} (PR {pr_status})")
                except VkMcpError as e:
                    log(f"  ! {simple_id}: status transition failed (non-fatal): {e}")


def fetch_existing_titles(client: VkMcpClient) -> set[str]:
    """Fetch existing VK card titles for dedup via MCP."""
    try:
        resp = client.list_issues(VK_DERIO_OPS_PROJECT, limit=200)
        issues = resp.get("issues", [])
        return {i["title"] for i in issues if isinstance(i, dict) and "title" in i}
    except VkMcpError as e:
        log(f"[warn] could not fetch existing cards for dedup: {e}")
        return set()


def count_active_ws(client: VkMcpClient) -> int:
    """Count non-archived workspaces with worktree present."""
    try:
        resp = client.list_workspaces(archived=False, limit=100)
        workspaces = resp.get("workspaces", [])
        return sum(1 for ws in workspaces if not ws.get("worktree_deleted", False))
    except VkMcpError as e:
        log(f"[warn] could not count active workspaces: {e}")
        return 0


def fetch_repo_names(client: VkMcpClient) -> set[str]:
    """Fetch known repo names from VK for validation."""
    try:
        resp = client.list_repos()
        repos = resp.get("repos", resp) if isinstance(resp, dict) else resp
        return {r["name"] for r in repos}
    except VkMcpError as e:
        log(f"[warn] could not fetch repo list: {e}")
        return set()


# --- Metrics ---

def _push_metric(text: str) -> None:
    """Push raw Prometheus exposition text to Pushgateway under our job."""
    url = f"{PUSHGATEWAY_URL}/metrics/job/vk_issue_bridge"
    try:
        req = urllib.request.Request(
            url, data=text.encode(), method="POST",
            headers={"Content-Type": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        log(f"[warn] pushgateway push failed: {e}")


def push_failure_metric(issue_id: str, reason: str) -> None:
    text = (
        '# TYPE willikins_vk_bridge_failure_total counter\n'
        f'willikins_vk_bridge_failure_total{{reason="{reason}",issue="{issue_id}"}} 1\n'
    )
    _push_metric(text)


def push_success_metric() -> None:
    text = (
        '# TYPE willikins_vk_bridge_sync_total counter\n'
        'willikins_vk_bridge_sync_total 1\n'
    )
    _push_metric(text)


def push_heartbeat() -> None:
    import time
    ts = int(time.time())
    text = (
        '# TYPE willikins_heartbeat_last_success_timestamp gauge\n'
        '# HELP willikins_heartbeat_last_success_timestamp Unix timestamp of last successful run\n'
        f'willikins_heartbeat_last_success_timestamp {ts}\n'
    )
    _push_metric(text)


# --- GitHub client ---

def gh_list_ready_issues() -> list[GhIssue]:
    """Find vk-ready Issues (across all known repos) that are not vk-synced."""
    issues: list[GhIssue] = []
    repo_names = discover_repos()
    log(f"[bridge] discovered repos: {repo_names}")
    for repo_name in repo_names:
        repo = f"derio-net/{repo_name}"
        try:
            out = subprocess.run(
                [
                    "gh", "issue", "list",
                    "--repo", repo,
                    "--label", GH_LABEL_READY,
                    "--state", "open",
                    "--json", "number,title,body,url,labels",
                    "--limit", "50",
                ],
                check=True, capture_output=True, text=True,
            ).stdout
        except subprocess.CalledProcessError as e:
            log(f"[warn] gh issue list failed for {repo}: {e.stderr}")
            continue

        for raw in json.loads(out):
            label_names = {l["name"] for l in raw.get("labels", [])}
            if GH_LABEL_SYNCED in label_names:
                continue
            issues.append(GhIssue(
                number=raw["number"],
                title=raw["title"],
                body=raw.get("body") or "",
                html_url=raw["url"],
                repo=repo,
                labels=tuple(l["name"] for l in raw.get("labels", [])),
            ))
    return issues


# --- Sync logic ---

def build_prompt(issue: GhIssue, parsed: ParsedBody) -> str:
    return (
        f"You are a VK-spawned agent working on GitHub Issue gh#{issue.number}:\n"
        f"{issue.title}\n\n"
        f"The Issue is at: {issue.html_url}\n"
        f"Repo: {parsed.repos[0]}\n\n"
        f"Use superpowers-for-vk:{parsed.skill} to implement this task.\n\n"
        "The full task description is in the GitHub Issue body — read it before "
        "starting. When you finish, open a PR. The lifecycle board will reflect "
        "your progress automatically."
    )


def sync_issue(issue: GhIssue, parsed: ParsedBody, client: VkMcpClient) -> bool:
    """Create VK card + workspace for one GitHub Issue. Returns True on success."""
    repo_name = parsed.repos[0]

    # 1. Create the VK kanban card
    try:
        card = client.create_issue(
            VK_DERIO_OPS_PROJECT,
            f"gh#{issue.number}: {issue.title}",
            description=issue.html_url,
        )
    except VkMcpError as e:
        log(f"  x {issue.repo}#{issue.number}: card creation failed: {e}")
        push_failure_metric(str(issue.number), "card_create_failed")
        return False

    card_id = card.get("id") or card.get("issue_id")
    if not card_id:
        log(f"  x {issue.repo}#{issue.number}: card creation returned no id: {card}")
        push_failure_metric(str(issue.number), "card_create_no_id")
        return False
    # Get simple_id from creation response or fetch it
    simple_id = card.get("simple_id", "?")
    if simple_id == "?":
        try:
            card_detail = client.get_issue(card_id)
            # get_issue wraps in {"issue": {...}}
            if isinstance(card_detail, dict) and "issue" in card_detail:
                card_detail = card_detail["issue"]
            simple_id = card_detail.get("simple_id", "?")
        except VkMcpError:
            pass
    log(f"  + {issue.repo}#{issue.number}: created card {simple_id} ({card_id})")

    # 2. Transition card to "In progress"
    try:
        client.update_issue(card_id, status="In progress")
    except VkMcpError as e:
        log(f"  ! {issue.repo}#{issue.number}: status transition failed (non-fatal): {e}")

    # 3. Find repo UUID by name for workspace creation
    try:
        resp = client.list_repos()
        repos = resp.get("repos", resp) if isinstance(resp, dict) else resp
        repo_uuid = None
        for r in repos:
            if r.get("name") == repo_name:
                repo_uuid = r["id"]
                break
        if not repo_uuid:
            log(f"  x {issue.repo}#{issue.number}: repo '{repo_name}' not found in VK")
            push_failure_metric(str(issue.number), "repo_not_found")
            return False
    except VkMcpError as e:
        log(f"  x {issue.repo}#{issue.number}: repo lookup failed: {e}")
        push_failure_metric(str(issue.number), "repo_lookup_failed")
        return False

    # 4. Create + start the workspace
    try:
        ws_resp = client.start_workspace(
            name=f"{simple_id} -> gh#{issue.number}",
            executor="CLAUDE_CODE",
            repositories=[{"repo_id": repo_uuid, "branch": "main"}],
            prompt=build_prompt(issue, parsed),
            issue_id=card_id,
        )
    except VkMcpError as e:
        log(f"  x {issue.repo}#{issue.number}: workspace creation failed: {e}")
        push_failure_metric(str(issue.number), "workspace_create_failed")
        return False

    ws_id = (ws_resp.get("id") or ws_resp.get("workspace_id") or "?") if isinstance(ws_resp, dict) else "?"
    log(f"  + {issue.repo}#{issue.number}: started workspace {ws_id}")

    # 5. Link workspace to card
    try:
        client.link_workspace_issue(ws_id, card_id)
        log(f"  + {issue.repo}#{issue.number}: linked workspace -> card {simple_id}")
    except VkMcpError as e:
        log(f"  ! {issue.repo}#{issue.number}: workspace-card link failed (non-fatal): {e}")
        push_failure_metric(str(issue.number), "link_failed")

    # 6. Label the GitHub Issue as synced (idempotency marker — non-fatal,
    #    workspace is already running so we must count this as synced)
    try:
        subprocess.run(
            ["gh", "issue", "edit", str(issue.number),
             "--repo", issue.repo, "--add-label", GH_LABEL_SYNCED],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        log(f"  ! {issue.repo}#{issue.number}: label add failed (non-fatal): {e.stderr.strip()}")
        push_failure_metric(str(issue.number), "label_failed")

    # 7. Transition the lifecycle board: plan -> in-progress (best-effort)
    try:
        subprocess.run(
            [TRANSITION_SCRIPT, issue.html_url, "in-progress"],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log(f"  ! {issue.repo}#{issue.number}: lifecycle transition failed (non-fatal)")
        push_failure_metric(str(issue.number), "lifecycle_failed")

    push_success_metric()
    ws_short = ws_id[:8] if isinstance(ws_id, str) and len(ws_id) > 8 else ws_id
    log(f"  v {issue.repo}#{issue.number}: synced (card={simple_id}, ws={ws_short})")
    return True


def main() -> int:
    log(f"[bridge] starting — dry_run={DRY_RUN}")

    # Fail fast if VK is unreachable
    try:
        client = VkMcpClient()
    except Exception as e:
        log(f"[fatal] cannot start VK MCP client: {e}")
        push_failure_metric("startup", "vk_unreachable")
        return 1

    try:
        vk_repo_names = fetch_repo_names(client)
        log(f"[bridge] vk repos: {sorted(vk_repo_names)}")

        existing_titles = fetch_existing_titles(client)
        log(f"[bridge] existing VK cards: {len(existing_titles)}")

        active_ws = count_active_ws(client)
        slots = max(0, MAX_CONCURRENT - active_ws)
        log(f"[bridge] active workspaces: {active_ws}, max: {MAX_CONCURRENT}, slots available: {slots}")

        issues = gh_list_ready_issues()
        log(f"[bridge] found {len(issues)} unsynced vk-ready issues")

        synced = 0
        skipped = 0
        failed = 0
        deferred = 0
        for i in issues:
            parsed = parse_issue_body(i.body)
            if parsed.parse_error:
                log(f"  x {i.repo}#{i.number}: PARSE ERROR — {parsed.parse_error}")
                failed += 1
                continue
            if parsed.repos[0] not in vk_repo_names:
                log(f"  x {i.repo}#{i.number}: unknown repo '{parsed.repos[0]}'")
                failed += 1
                continue

            # Extract phase number from labels for fail-loud dependency gating
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

            # Dependency gating: skip if blockers are still open
            if deps:
                open_blockers = check_blockers(i.repo, deps)
                if open_blockers:
                    blocker_str = ", ".join(open_blockers)
                    log(f"  p {i.repo}#{i.number}: blocked by {blocker_str}")
                    deferred += 1
                    continue

            if DRY_RUN:
                log(f"  > {i.repo}#{i.number}: WOULD SYNC ({parsed.skill}, {parsed.repos[0]})")
                skipped += 1
                continue

            # Check if this is a dedup-only sync (card exists, just needs label)
            expected_title = f"gh#{i.number}: {i.title}"
            is_dedup = expected_title in existing_titles

            if is_dedup:
                log(f"  = {i.repo}#{i.number}: card already exists in VK, labelling synced")
                try:
                    subprocess.run(
                        ["gh", "issue", "edit", str(i.number),
                         "--repo", i.repo, "--add-label", GH_LABEL_SYNCED],
                        check=True, capture_output=True, text=True,
                    )
                except subprocess.CalledProcessError:
                    pass
                synced += 1
                continue

            if slots <= 0:
                log(f"  ~ {i.repo}#{i.number}: deferred — no workspace slots available")
                deferred += 1
                continue

            if sync_issue(i, parsed, client):
                synced += 1
                slots -= 1
            else:
                failed += 1

        log(f"[bridge] summary: {synced} synced, {skipped} dry-run, {failed} failed, {deferred} deferred")

        # PR-status polling
        log("[bridge] polling PR status for active cards...")
        poll_pr_status(client)

        push_heartbeat()
        return 1 if failed > 0 else 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
