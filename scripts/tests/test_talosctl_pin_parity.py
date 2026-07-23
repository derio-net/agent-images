"""Guard: talosctl/omnictl pin parity, and talosctl tracking the cluster.

Two failure modes, both silent:

1. `TALOSCTL_VERSION` lives in TWO Dockerfiles (infra-shell, kali). Nothing
   makes them move together, so they can drift apart and one shell quietly
   ships a different client than the other.

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
PINNED_IN = ["infra-shell/Dockerfile", "kali/Dockerfile"]


def _arg(dockerfile: str, name: str) -> str:
    text = (REPO_ROOT / dockerfile).read_text()
    m = re.search(rf"^ARG\s+{name}=(.+)$", text, re.MULTILINE)
    assert m, f"{name} not found in {dockerfile}"
    return m.group(1).strip()


@pytest.mark.parametrize("name", ["TALOSCTL_VERSION", "OMNICTL_VERSION"])
def test_pin_is_identical_across_both_dockerfiles(name):
    values = {df: _arg(df, name) for df in PINNED_IN}
    assert len(set(values.values())) == 1, (
        f"{name} has drifted between shells: {values}"
    )


def test_talosctl_matches_the_cluster_not_upstream_latest():
    """The cluster's version is the target. Upstream latest is NOT - pinning
    there puts the client ahead of the nodes and re-creates the skew in the
    other direction the moment the cluster lags."""
    for df in PINNED_IN:
        assert _arg(df, "TALOSCTL_VERSION") == LAST_MEASURED_CLUSTER_TALOS, (
            f"{df} pins talosctl at {_arg(df, 'TALOSCTL_VERSION')}, but the "
            f"cluster runs {LAST_MEASURED_CLUSTER_TALOS}"
        )
