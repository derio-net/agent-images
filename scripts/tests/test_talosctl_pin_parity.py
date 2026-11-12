"""Guard: talosctl/omnictl pin parity, and talosctl tracking the cluster.

Two failure modes, both silent:

1. A pin that lives in more than one Dockerfile can drift apart, so one image
   quietly ships a different client than the other. `OMNICTL_VERSION` lives
   in two (infra-shell, upgrade-session). `TALOSCTL_VERSION` lived in two
   until secure-agent-kali was retired (2026-11); infra-shell is now its only
   home, and a second copy appearing anywhere unlisted fails here.

2. The pin can fall behind the cluster. Talos supports only +/-1 minor of
   client skew; on 2026-07-23 the shells shipped v1.9.5 against a v1.12.6
   cluster - three minors out, with no alert and no symptom until a command
   needed the newer API.

`LAST_MEASURED_CLUSTER_TALOS` in version_audit.py is the single source of truth
for what the cluster is running. When the cluster is upgraded, update that
constant and this test tells you which Dockerfiles still need the bump.
"""
import re
from pathlib import Path

import pytest

from version_audit import LAST_MEASURED_CLUSTER_TALOS

REPO_ROOT = Path(__file__).resolve().parents[2]
# Every Dockerfile that declares each pin. The lists are asserted against the
# tree, so a new copy of a pin cannot be added without joining its parity check.
PINNED_IN = {
    "TALOSCTL_VERSION": ["infra-shell/Dockerfile"],
    "OMNICTL_VERSION": ["infra-shell/Dockerfile", "upgrade-session/Dockerfile"],
}


def _arg(dockerfile: str, name: str) -> str:
    text = (REPO_ROOT / dockerfile).read_text()
    m = re.search(rf"^ARG\s+{name}=(.+)$", text, re.MULTILINE)
    assert m, f"{name} not found in {dockerfile}"
    return m.group(1).strip()


def _declared_in(name: str) -> list[str]:
    return sorted(
        str(df.relative_to(REPO_ROOT))
        for df in REPO_ROOT.glob("*/Dockerfile")
        if re.search(rf"^ARG\s+{name}=", df.read_text(), re.MULTILINE)
    )


@pytest.mark.parametrize("name", sorted(PINNED_IN))
def test_pinned_in_lists_every_dockerfile_that_declares_the_pin(name):
    """Parity is only checked across PINNED_IN, so the list has to be complete:
    an unlisted second copy would drift with nothing watching it."""
    assert _declared_in(name) == sorted(PINNED_IN[name])


@pytest.mark.parametrize("name", sorted(PINNED_IN))
def test_pin_is_identical_across_its_dockerfiles(name):
    # upgrade-session carries omnictl but not TALOSCTL_VERSION: it pins one
    # talosctl per minor under TALOSCTL_<minor>_VERSION instead.
    values = {df: _arg(df, name) for df in PINNED_IN[name]}
    assert len(set(values.values())) == 1, (
        f"{name} has drifted between images: {values}"
    )


def test_talosctl_matches_the_cluster_not_upstream_latest():
    """The cluster's version is the target. Upstream latest is NOT - pinning
    there puts the client ahead of the nodes and re-creates the skew in the
    other direction the moment the cluster lags."""
    for df in PINNED_IN["TALOSCTL_VERSION"]:
        assert _arg(df, "TALOSCTL_VERSION") == LAST_MEASURED_CLUSTER_TALOS, (
            f"{df} pins talosctl at {_arg(df, 'TALOSCTL_VERSION')}, but the "
            f"cluster runs {LAST_MEASURED_CLUSTER_TALOS}"
        )
