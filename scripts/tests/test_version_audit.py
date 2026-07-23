"""Guard: the version audit must see every version-bearing pin in the repo.

There is no upstream watcher for this repo, so every pin drifts untracked until
someone measures by hand. On 2026-07-23 that measurement found `talosctl` three
minor versions behind the cluster it talks to — outside Talos's supported +/-1
skew — with no alert and no symptom until a command needed the newer API.

The audit is registry-driven rather than heuristic on purpose. A regex that
guesses which ARGs are versions fails *silently* on the pin it doesn't
recognise, which is the exact failure mode this whole exercise exists to fix.
`test_no_uncovered_version_args` is therefore the load-bearing test: it fails
loudly when someone adds a version-shaped ARG without registering it.
"""
from pathlib import Path

import pytest

from version_audit import (
    PIN_SPECS,
    extract_pins,
    find_uncovered_version_args,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pins():
    return {p.name: p for p in extract_pins(REPO_ROOT)}


# --- extraction ------------------------------------------------------------


def test_extracts_a_representative_pin(pins):
    assert "SUPERCRONIC_VERSION" in pins
    assert pins["SUPERCRONIC_VERSION"].current
    assert any(f.endswith("base/Dockerfile") for f in pins["SUPERCRONIC_VERSION"].files)


def test_talosctl_and_omnictl_report_both_locations(pins):
    """These two live in TWO Dockerfiles each, and the silent failure is the
    pair drifting apart. Collapsing them to one location hides that."""
    for name in ("TALOSCTL_VERSION", "OMNICTL_VERSION"):
        files = pins[name].files
        assert len(files) == 2, f"{name} should be found in 2 Dockerfiles, got {files}"
        assert any(f.endswith("infra-shell/Dockerfile") for f in files)
        assert any(f.endswith("kali/Dockerfile") for f in files)


def test_hermes_tag_is_sourced_from_dockerhub(pins):
    """HERMES_TAG is consumed by a FROM line, so its upstream is Docker Hub -
    not a bare ARG default with no registry behind it."""
    pin = pins["HERMES_TAG"]
    assert pin.source == "dockerhub"
    assert pin.source_ref == "nousresearch/hermes-agent"


def test_major_only_pin_is_not_dropped(pins):
    """NODE_MAJOR=22 has no dots. A semver-shaped regex silently loses it."""
    assert "NODE_MAJOR" in pins
    assert pins["NODE_MAJOR"].current == "22"


def test_unpinned_claude_code_is_reported_not_omitted(pins):
    """base installs @anthropic-ai/claude-code with no version at all. An
    absent pin is a finding, not a reason to leave it out of the report."""
    pin = pins["@anthropic-ai/claude-code"]
    assert pin.current is None
    assert pin.unpinned is True


# --- classification --------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["CODEX_VERSION", "OPENCODE_VERSION", "@anthropic-ai/claude-code"],
)
def test_bootstrap_pins_are_classified_bootstrap(pins, name):
    """These are first-boot seeds only: the CLI self-updates in-pod and floats
    forward via the shell inventory's `harnesses:` key, so bumping them changes
    what a FRESH PVC starts from and nothing else."""
    assert pins[name].classification == "bootstrap"


@pytest.mark.parametrize(
    "name",
    [
        "TALOSCTL_VERSION",
        "S6_OVERLAY_VERSION",
        "SUPERCRONIC_VERSION",
        "RUFLO_GIT_REF",
        "NODE_MAJOR",
    ],
)
def test_rebuild_only_pins_are_classified_rebuild_only(pins, name):
    """For these the image rebuild is the ONLY refresh path, so staleness is
    real. The report ranks by this, not by release count."""
    assert pins[name].classification == "rebuild-only"


# --- coverage (the load-bearing guard) -------------------------------------


def test_no_uncovered_version_args():
    """A version-shaped ARG with no PIN_SPECS entry is invisible to the audit.

    This is the guard that makes the registry safe: add a pin to a Dockerfile
    without registering it and this fails, rather than the audit quietly under-
    reporting forever.
    """
    uncovered = find_uncovered_version_args(REPO_ROOT)
    assert not uncovered, (
        "version-shaped ARG(s) not in PIN_SPECS - add an entry (or an explicit "
        f"ignore) in scripts/version_audit.py: {uncovered}"
    )


def test_every_spec_is_actually_found_in_the_tree():
    """The inverse: a registry entry whose ARG no longer exists is dead weight
    that makes the report claim coverage it doesn't have."""
    found = {p.name for p in extract_pins(REPO_ROOT)}
    missing = sorted(set(PIN_SPECS) - found)
    assert not missing, f"PIN_SPECS entries with no match in the tree: {missing}"
