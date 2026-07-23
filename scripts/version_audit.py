"""On-demand upstream-version audit for the agent-images pins.

Why this exists
---------------
Nothing watches the version pins in this repo. Between hand-measurements they
drift silently, and on 2026-07-23 a hand-measurement found `talosctl` three
minor versions behind the cluster it talks to (v1.9.5 vs v1.12.6) - outside
Talos's supported +/-1 client skew, with no alert and no symptom until a command
happened to need the newer API.

This script answers "what has drifted, and which of it matters" on demand. It is
deliberately NOT a scheduled workflow opening drift PRs: it is a report, not a
gate, and it exits 0 unless asked otherwise.

Two design decisions worth keeping
----------------------------------
1. **Registry-driven, not heuristic.** `PIN_SPECS` is an explicit table. A regex
   that guesses which ARGs are versions fails *silently* on the pin it doesn't
   recognise - the exact failure mode this script exists to catch.
   `find_uncovered_version_args()` closes the loop: a version-shaped ARG with no
   registry entry is a loud test failure, not a quiet omission.

2. **"Latest" is the WRONG target for two pins.** `talosctl` must track the
   *cluster's* Talos version and `omnictl` the *Omni server's* version - not the
   newest upstream release. Pinning either to latest re-creates the same skew in
   the opposite direction the moment the infrastructure lags. Those two carry an
   `anchor`, and when the anchor cannot be probed the target is reported
   `unknown` rather than falling back to latest: a confident wrong answer is
   worse than an honest gap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# --- the registry ----------------------------------------------------------
#
# classification:
#   bootstrap    - the Dockerfile line is only a first-boot seed; the tool
#                  self-updates in-pod and floats forward via the shell
#                  inventory's `harnesses:` key. Bumping changes what a FRESH
#                  PVC starts from and nothing else.
#   rebuild-only - the image rebuild is the ONLY refresh path. This is where
#                  staleness becomes real, and what the report ranks by.
#
# anchor (optional) - the pin must track a piece of LIVE infrastructure rather
#   than the newest upstream release. See the module docstring.

# The cluster's Talos version, last measured 2026-07-23 (all 7 Frank nodes on
# v1.12.6). This is the TARGET for TALOSCTL_VERSION - not upstream latest.
#
# When the cluster is upgraded, update this constant; `test_talosctl_pin_parity`
# then tells you which Dockerfiles still need the bump. That is the whole
# mechanism keeping the client inside Talos's supported +/-1 minor skew, which
# is what silently broke: the shells sat at v1.9.5 against v1.12.6.
LAST_MEASURED_CLUSTER_TALOS = "v1.12.6"

PIN_SPECS: dict[str, dict] = {
    # --- rebuild-only, anchored to live infrastructure ---------------------
    "TALOSCTL_VERSION": {
        "source": "github-release",
        "source_ref": "siderolabs/talos",
        "classification": "rebuild-only",
        "anchor": "cluster",
        "note": "Must equal the CLUSTER's Talos version - Talos supports only "
                "+/-1 minor of client skew. Latest is the wrong target.",
    },
    "OMNICTL_VERSION": {
        "source": "github-release",
        "source_ref": "siderolabs/omni",
        "classification": "rebuild-only",
        "anchor": "omni-server",
        "note": "Must track the running Omni SERVER. The server version is not "
                "recorded in this repo (it lives in omni.env on the Omni host).",
    },
    # --- rebuild-only, plain upstream --------------------------------------
    "S6_OVERLAY_VERSION": {
        "source": "github-release",
        "source_ref": "just-containers/s6-overlay",
        "classification": "rebuild-only",
        "note": "PID 1 in every agent shell - a regression stops containers "
                "booting rather than degrading a feature.",
    },
    "SUPERCRONIC_VERSION": {
        "source": "github-release",
        "source_ref": "aptible/supercronic",
        "classification": "rebuild-only",
    },
    "MICROMAMBA_VERSION": {
        "source": "github-release",
        "source_ref": "mamba-org/micromamba-releases",
        "classification": "rebuild-only",
    },
    "HINDSIGHT_API_VERSION": {
        "source": "pypi",
        "source_ref": "hindsight-api",
        "classification": "rebuild-only",
    },
    "TORCH_VERSION": {
        "source": "pypi",
        "source_ref": "torch",
        "classification": "rebuild-only",
    },
    "HERMES_VERSION": {
        "source": "pypi",
        "source_ref": "hermes-agent",
        "classification": "rebuild-only",
        "note": "Seeds a relocatable venv that is copied onto the PVC behind a "
                ".seed-version marker - the image shipping N does NOT prove the "
                "pod runs N. Verify with `hermes --version` inside the pod.",
    },
    "HERMES_TAG": {
        "source": "dockerhub",
        "source_ref": "nousresearch/hermes-agent",
        "classification": "rebuild-only",
    },
    "TMUX_RESURRECT_REF": {
        "source": "github-tag",
        "source_ref": "tmux-plugins/tmux-resurrect",
        "classification": "rebuild-only",
        "note": "Publishes TAGS, not releases - a /releases/latest lookup 404s.",
    },
    "TMUX_CONTINUUM_REF": {
        "source": "github-tag",
        "source_ref": "tmux-plugins/tmux-continuum",
        "classification": "rebuild-only",
        "note": "Publishes TAGS, not releases - a /releases/latest lookup 404s.",
    },
    "NODE_MAJOR": {
        "source": "none",
        "classification": "rebuild-only",
        "note": "Major-only pin (no dots). Rebases the runtime under every "
                "shell and under the npm-global harnesses installed against it.",
    },
    "RUFLO_GIT_REF": {
        "source": "git-ref",
        "source_ref": "ruvnet/ruflo",
        "classification": "rebuild-only",
        "subtree": "ruflo/src/ruvocal",
        "note": "MONOREPO. Measure drift at the subtree actually built, not at "
                "repo HEAD - and by tree/blob SHA, because the compare API caps "
                ".files[] at 300 entries and will report a false 'no changes'.",
    },
    # --- bootstrap ----------------------------------------------------------
    "CODEX_VERSION": {
        "source": "npm",
        "source_ref": "@openai/codex",
        "classification": "bootstrap",
    },
    "OPENCODE_VERSION": {
        "source": "npm",
        "source_ref": "opencode-ai",
        "classification": "bootstrap",
    },
    "@anthropic-ai/claude-code": {
        "source": "npm",
        "source_ref": "@anthropic-ai/claude-code",
        "classification": "bootstrap",
        "unpinned_in": "base/Dockerfile",
        "note": "Installed with NO version - floats to whatever npm publishes at "
                "build time. Reported so the absence is visible, not silent.",
    },
    # --- deliberately frozen -----------------------------------------------
    "RUFLO_ENV_FALLBACK_SHA": {
        "source": "none",
        "classification": "rebuild-only",
        "frozen": True,
        "note": "NOT a version. Historical anchor: the last commit where "
                "ruvocal's .env was still tracked upstream. Bumping it breaks "
                "the build-time defaults fetch.",
    },
    "BGE_REVISION": {
        "source": "none",
        "classification": "rebuild-only",
        "frozen": True,
        "note": "A HuggingFace MODEL revision, not a software version - moving "
                "it changes embedding behaviour. Belongs to a Hindsight-quality "
                "decision, not a version sweep.",
    },
}

# ARGs that look version-ish but are build plumbing, not upstream pins.
IGNORED_ARGS = {
    "BASE_SHA",            # this repo's own parent-image SHA, set by CI
    "AGENT_BASE_SHA",      # ditto
    "VK_FORK_SHA",         # built from our own vibe-kanban fork by another pipeline
    "TARGETARCH",
    "AGENT_USER", "AGENT_UID", "AGENT_GID", "AGENT_HOME",
}

_ARG_RE = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(.*?)\s*$")
# A value that looks like something with an upstream: 1.2.3, v1.2, a 40-hex SHA,
# a calver tag, or a bare major.
_VERSIONISH_VALUE = re.compile(r"^v?\d+(\.\d+)*$|^[0-9a-f]{40}$|^v\d{4}\.\d+")
_VERSIONISH_NAME = re.compile(r"(VERSION|_REF|_TAG|_SHA|_MAJOR|MAJOR)$")


@dataclass
class Pin:
    name: str
    current: str | None
    files: list[str] = field(default_factory=list)
    source: str = "none"
    source_ref: str | None = None
    classification: str = "rebuild-only"
    anchor: str | None = None
    subtree: str | None = None
    frozen: bool = False
    unpinned: bool = False
    note: str | None = None


def _dockerfiles(repo_root: Path) -> list[Path]:
    """Every image Dockerfile, excluding nested worktrees (which are copies and
    would double-count every pin)."""
    return sorted(
        p for p in repo_root.glob("*/Dockerfile")
        if "worktrees" not in str(p.relative_to(repo_root))
    )


def _scan_args(repo_root: Path) -> dict[str, tuple[str, list[str]]]:
    """name -> (value, [relative dockerfile paths])."""
    found: dict[str, tuple[str, list[str]]] = {}
    for df in _dockerfiles(repo_root):
        rel = str(df.relative_to(repo_root))
        for line in df.read_text().splitlines():
            m = _ARG_RE.match(line)
            if not m:
                continue
            name, value = m.group(1), m.group(2).strip()
            if not value:
                continue
            if name in found:
                prev_value, files = found[name]
                if rel not in files:
                    files.append(rel)
                # Keep the first value; a mismatch across files is exactly what
                # the talosctl/omnictl parity test is there to catch.
                found[name] = (prev_value, files)
            else:
                found[name] = (value, [rel])
    return found


def extract_pins(repo_root: Path) -> list[Pin]:
    """Every registered pin present in the tree, with its live current value."""
    repo_root = Path(repo_root)
    scanned = _scan_args(repo_root)
    pins: list[Pin] = []

    for name, spec in PIN_SPECS.items():
        unpinned_in = spec.get("unpinned_in")
        if unpinned_in:
            # No ARG to read - the pin's absence IS the finding. Only report it
            # if the install line is genuinely still there and still unpinned.
            target = repo_root / unpinned_in
            if not target.exists():
                continue
            if f"npm install -g {name}\n" not in target.read_text() + "\n":
                continue
            pins.append(Pin(
                name=name, current=None, files=[unpinned_in], unpinned=True,
                source=spec.get("source", "none"),
                source_ref=spec.get("source_ref"),
                classification=spec["classification"],
                note=spec.get("note"),
            ))
            continue

        if name not in scanned:
            continue
        value, files = scanned[name]
        pins.append(Pin(
            name=name, current=value, files=files,
            source=spec.get("source", "none"),
            source_ref=spec.get("source_ref"),
            classification=spec["classification"],
            anchor=spec.get("anchor"),
            subtree=spec.get("subtree"),
            frozen=spec.get("frozen", False),
            note=spec.get("note"),
        ))
    return pins


# --- upstream resolution ---------------------------------------------------


def default_fetch(url: str):
    """Single network seam. Everything else in this module is pure, so the
    tests replace exactly this and stay offline."""
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "agent-images-version-audit"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FileNotFoundError(url) from exc
        raise


def _github_tags_latest(repo: str, fetch):
    tags = fetch(f"https://api.github.com/repos/{repo}/tags")
    return tags[0]["name"] if tags else None


# Docker Hub tags that move. Pinning to one defeats the point of pinning.
_FLOATING_TAGS = {"latest", "main", "master", "edge", "nightly", "canary"}


def resolve_latest(pin: "Pin", fetch=default_fetch) -> str | None:
    """The newest upstream version for a pin, or None when there is no upstream
    to ask or it could not be reached.

    Never raises on an unreachable upstream: an audit that dies on one flaky
    registry reports nothing about the other fifteen pins.
    """
    ref = pin.source_ref
    try:
        if pin.source == "npm":
            return fetch(f"https://registry.npmjs.org/{ref}/latest")["version"]

        if pin.source == "pypi":
            return fetch(f"https://pypi.org/pypi/{ref}/json")["info"]["version"]

        if pin.source == "github-release":
            try:
                return fetch(f"https://api.github.com/repos/{ref}/releases/latest")["tag_name"]
            except FileNotFoundError:
                # Real upstreams (tmux-resurrect, tmux-continuum) publish tags
                # and no releases. Falling back keeps them from reading as
                # "unknown" when they are in fact current.
                return _github_tags_latest(ref, fetch)

        if pin.source == "github-tag":
            return _github_tags_latest(ref, fetch)

        if pin.source == "dockerhub":
            payload = fetch(
                f"https://hub.docker.com/v2/repositories/{ref}/tags"
                "?page_size=25&ordering=last_updated"
            )
            for tag in payload.get("results", []):
                if tag["name"] not in _FLOATING_TAGS:
                    return tag["name"]
            return None

        if pin.source == "git-ref":
            commits = fetch(f"https://api.github.com/repos/{ref}/commits?per_page=1")
            return commits[0]["sha"] if commits else None
    except (FileNotFoundError, KeyError, IndexError, OSError):
        return None

    return None


def resolve_target(pin: "Pin", probes: dict, fetch=default_fetch) -> str | None:
    """What this pin SHOULD be set to.

    For most pins that is upstream latest. For the two anchored pins it is the
    version of a live piece of infrastructure - and if that cannot be probed the
    answer is None ("unknown"), never a fallback to latest. See the module
    docstring: for talosctl and omnictl, latest is a wrong answer, and a
    confident wrong answer is worse than an honest gap.
    """
    if pin.anchor:
        probe = probes.get(pin.anchor)
        if probe is None:
            return None
        try:
            return probe()
        except Exception:
            return None
    return resolve_latest(pin, fetch=fetch)


def probe_cluster_talos_version() -> str:
    """The cluster's Talos version, read from any node's osImage."""
    import re as _re
    import subprocess

    out = subprocess.run(
        ["kubectl", "get", "nodes", "-o",
         "jsonpath={.items[0].status.nodeInfo.osImage}"],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    m = _re.search(r"v?(\d+\.\d+\.\d+)", out)
    if not m:
        raise RuntimeError(f"could not parse Talos version from osImage: {out!r}")
    return f"v{m.group(1)}"


# --- reporting -------------------------------------------------------------


class Status(str, Enum):
    CURRENT = "current"
    BEHIND = "behind"
    UNKNOWN = "unknown"
    FROZEN = "frozen"
    UNPINNED = "unpinned"


# A trailing packaging revision: micromamba pins `2.8.1` but tags its release
# `2.8.1-0`. Only pure digits after the dash - an alphanumeric suffix (`-rc1`,
# `-beta`) is a genuinely different version and must still read as drift.
_PACKAGING_REVISION = re.compile(r"-\d+$")


def _normalise(version: str) -> str:
    """Pins are written inconsistently (`0.2.33` vs `v0.2.47`, `2.8.1` vs
    `2.8.1-0`). Without this a perfectly current pin reads as behind, someone
    chases a no-op bump - and a report with false positives stops being read."""
    return _PACKAGING_REVISION.sub("", version.lstrip("vV").strip())


def classify_status(pin: "Pin", target: str | None) -> Status:
    if pin.unpinned:
        return Status.UNPINNED
    if pin.frozen:
        # Deliberate anchors, not stale pins. Reporting them as drift invites
        # someone to "fix" them and break the build.
        return Status.FROZEN
    if target is None or pin.current is None:
        return Status.UNKNOWN
    if _normalise(pin.current) == _normalise(target):
        return Status.CURRENT
    return Status.BEHIND


_STATUS_MARK = {
    Status.CURRENT: "ok",
    Status.BEHIND: "BEHIND",
    Status.UNKNOWN: "unknown",
    Status.FROZEN: "frozen",
    Status.UNPINNED: "UNPINNED",
}


def render_report(pins, targets: dict, with_exit_code: bool = False):
    """Group by classification, because that - not release count - is what says
    whether drift is worth acting on.

    Always exits 0. This is an on-demand report for a human, not a gate; a
    non-zero exit is an invitation to wire it into CI as a blocking check, and a
    blocking check on upstream drift fails for reasons nobody in the PR caused.
    """
    lines: list[str] = ["agent-images upstream version audit", ""]

    for classification, heading, blurb in (
        ("rebuild-only", "rebuild-only pins",
         "the image rebuild is the ONLY refresh path - staleness here is real"),
        ("bootstrap", "bootstrap pins",
         "first-boot seeds only; the tool self-updates in-pod via the "
         "inventory `harnesses:` key"),
    ):
        group = [p for p in pins if p.classification == classification]
        if not group:
            continue
        lines.append(f"## {heading} - {blurb}")
        for pin in sorted(group, key=lambda p: p.name):
            target = targets.get(pin.name)
            status = classify_status(pin, target)
            row = (f"  [{_STATUS_MARK[status]:>8}]  {pin.name:<24} "
                   f"{pin.current or '(none)':<44} -> {target or '?'}")
            if pin.anchor:
                # Without this a reader "helpfully" bumps talosctl to latest.
                row += f"   (target: {pin.anchor}, NOT upstream latest)"
            lines.append(row)
            if status in (Status.BEHIND, Status.UNKNOWN, Status.UNPINNED) and pin.note:
                lines.append(f"              note: {pin.note}")
            if len(pin.files) > 1:
                lines.append(f"              in: {', '.join(pin.files)}")
        lines.append("")

    text = "\n".join(lines)
    return (text, 0) if with_exit_code else text


def find_uncovered_version_args(repo_root: Path) -> list[str]:
    """Version-shaped ARGs with no PIN_SPECS entry and no explicit ignore.

    This is what keeps a registry honest: without it, adding a pin to a
    Dockerfile silently shrinks the audit's coverage instead of failing.
    """
    uncovered = []
    for name, (value, _files) in _scan_args(Path(repo_root)).items():
        if name in PIN_SPECS or name in IGNORED_ARGS:
            continue
        if _VERSIONISH_NAME.search(name) or _VERSIONISH_VALUE.match(value):
            uncovered.append(f"{name}={value}")
    return sorted(uncovered)


def probe_omni_server_version() -> str:
    """Not implementable from this repo: the running Omni server's version
    lives in an `omni.env` on the Omni host (omni/omni/compose.yaml only
    interpolates ${OMNI_IMG_TAG}). Raising here is what makes the omnictl row
    report `unknown` instead of silently falling back to upstream latest."""
    raise RuntimeError(
        "Omni server version is not discoverable from this repo - read it from "
        "omni.env on the Omni host, then pin OMNICTL_VERSION to it by hand"
    )


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--no-cluster", action="store_true",
        help="skip the kubectl probe (talosctl then reports 'unknown')",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    pins = extract_pins(repo_root)

    probes = {"omni-server": probe_omni_server_version}
    if not args.no_cluster:
        probes["cluster"] = probe_cluster_talos_version

    targets = {p.name: resolve_target(p, probes=probes) for p in pins}
    text, code = render_report(pins, targets=targets, with_exit_code=True)
    print(text)

    uncovered = find_uncovered_version_args(repo_root)
    if uncovered:
        print("WARNING - version-shaped ARGs missing from PIN_SPECS: "
              + ", ".join(uncovered))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
