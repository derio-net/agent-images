# Dynamic Repo Discovery for vk-issue-bridge

**Date:** 2026-04-13
**Status:** Approved

## Problem

`scripts/vk-issue-bridge.py` hardcodes a `KNOWN_REPOS` list on line 41. Adding a
new repo requires editing the script and rebuilding the container image. Repos
cloned to `~/repos` at runtime (on the PVC) are invisible to the bridge until
the image is rebuilt.

## Solution

Replace the hardcoded `KNOWN_REPOS` list with a `discover_repos()` function that
scans `~/repos` for git repositories at runtime. Every 2-minute cron invocation
discovers the current set of repos automatically.

## Design

### `discover_repos(repos_dir)` function

- Accepts a directory path (default from `REPOS_DIR` constant)
- `REPOS_DIR` defaults to `/home/claude/repos`, overridable via `VK_REPOS_DIR`
  env var
- Scans first-level entries using `os.scandir(repos_dir)`
- Includes an entry if it is a directory and contains a `.git` subdirectory
- Returns a sorted list of directory names (e.g. `["frank", "kid-laptops", ...]`)
- If `repos_dir` does not exist or is empty, returns `[]` and logs a warning

### Integration into `gh_list_ready_issues()`

- Calls `discover_repos()` at the top of the function instead of referencing the
  module-level `KNOWN_REPOS` constant
- The discovered list is logged for observability (similar to the existing VK
  repos log on line 479)

### What stays the same

- The `derio-net/` GitHub org prefix remains hardcoded
- All other logic (issue parsing, VK card creation, workspace management,
  dependency gating, PR polling, metrics) is untouched
- Cron schedule, permissions, and script location are unchanged

### Testing

- Unit test for `discover_repos()` using a temporary directory with a mix of
  git dirs, non-git dirs, and files to verify correct filtering
- Existing tests updated if they reference `KNOWN_REPOS`

### Observability

- The bridge logs the discovered repo list each run, e.g.
  `[bridge] discovered repos: ['frank', 'kid-laptops', ...]`

## Scope

- **In scope:** Replace hardcoded list, add discovery function, add test, add
  log line
- **Out of scope:** Deriving GitHub org from remote URL, exclusion mechanisms,
  config files
