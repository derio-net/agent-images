"""Guard: a Hermes version bump must actually reach a running pod.

The Hermes venv is built as a relocatable SEED at /opt/hermes-agent and copied
onto the /home/agent PVC on first boot. The copy is gated by a `.seed-version`
marker: cont-init.d/35-hermes-venv-seed re-seeds only when the seed's marker
differs from the live one.

So if the marker were ever a literal string rather than a function of
HERMES_VERSION, bumping the version would ship a new venv in the image while
every existing pod kept serving the OLD one off its PVC - image says 0.19.0,
pod says 0.15.2, everything green. This test makes that impossible.
"""
import re
from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[2]
              / "hermes-agent-shell" / "Dockerfile")
SEED_HOOK = (Path(__file__).resolve().parents[2] / "hermes-agent-shell"
             / "rootfs" / "etc" / "cont-init.d" / "35-hermes-venv-seed")


def test_seed_marker_is_derived_from_the_pinned_version():
    """The marker must interpolate ${HERMES_VERSION} - a literal would freeze
    every existing PVC at whatever it seeded first."""
    text = DOCKERFILE.read_text()
    marker_lines = [ln for ln in text.splitlines() if ".seed-version" in ln]
    assert marker_lines, "no .seed-version write found in the Dockerfile"
    assert any("${HERMES_VERSION}" in ln for ln in marker_lines), (
        "the .seed-version marker must be derived from ${HERMES_VERSION}, else "
        f"a version bump never re-seeds an existing PVC: {marker_lines}"
    )


def test_seed_hook_compares_seed_marker_against_live_marker():
    """The re-seed is only version-aware if the hook actually compares the two
    markers rather than checking mere existence of the live venv."""
    hook = SEED_HOOK.read_text()
    assert '"$SEED/.seed-version"' in hook
    assert '"$LIVE/.seed-version"' in hook


def test_pinned_version_is_a_concrete_release():
    """A floating spec (>=, *, latest) would make the image unreproducible and
    the marker meaningless."""
    m = re.search(r"^ARG HERMES_VERSION=(.+)$", DOCKERFILE.read_text(), re.MULTILINE)
    assert m, "HERMES_VERSION not found"
    assert re.fullmatch(r"\d+\.\d+\.\d+", m.group(1).strip()), (
        f"HERMES_VERSION must be an exact release, got {m.group(1)!r}"
    )
