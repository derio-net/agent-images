"""Contract for upgrade-session/Dockerfile (frank spec Part 3, R20-R23).

The image is a disposable upgrade-session pod: omnictl, a talosctl per Talos
minor in the upgrade window, a kubectl per Kubernetes minor, side by side,
selected per step. These tests read the Dockerfile text, like
test_talosctl_pin_parity.py.
"""
import re
from pathlib import Path

import pytest

from version_audit import LAST_MEASURED_CLUSTER_TALOS, PIN_SPECS

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "upgrade-session" / "Dockerfile"
TALOS_MINORS = ["1.12", "1.13", "1.14"]
K8S_MINORS = ["1.34", "1.35", "1.36", "1.37"]


@pytest.fixture(scope="module")
def text() -> str:
    assert DOCKERFILE.exists(), "upgrade-session/Dockerfile missing"
    return DOCKERFILE.read_text()


def _arg(text: str, name: str) -> str:
    m = re.search(rf"^ARG\s+{name}=(.+)$", text, re.MULTILINE)
    assert m, f"ARG {name} not found"
    return m.group(1).strip()


def _slug(minor: str) -> str:
    return minor.replace(".", "_")


def test_built_from_agent_base_not_the_s6_lineage(text):
    # s6-overlay's /init needs a writable /run and cont-init writes under
    # /var; that defeats a read-only root FS. agent-base is tini + non-root.
    assert re.search(r"^FROM\s+ghcr\.io/derio-net/agent-base:", text, re.M)


@pytest.mark.parametrize("minor", TALOS_MINORS)
def test_talosctl_pinned_exact_per_minor(text, minor):
    v = _arg(text, f"TALOSCTL_{_slug(minor)}_VERSION")
    assert re.fullmatch(rf"v{re.escape(minor)}\.\d+", v), v


@pytest.mark.parametrize("minor", K8S_MINORS)
def test_kubectl_pinned_exact_per_minor(text, minor):
    v = _arg(text, f"KUBECTL_{_slug(minor)}_VERSION")
    assert re.fullmatch(rf"v{re.escape(minor)}\.\d+", v), v


def test_window_contains_the_clusters_talos_minor():
    # Talos allows +/-1 minor of client skew; the cluster's own minor must be
    # a selectable one or no step can ever talk to the current cluster.
    m = re.match(r"v(\d+\.\d+)\.", LAST_MEASURED_CLUSTER_TALOS)
    assert m.group(1) in TALOS_MINORS


def test_no_unpinned_kubectl(text):
    assert "stable.txt" not in text


def test_omnictl_pin_matches_infra_shell(text):
    infra = (REPO_ROOT / "infra-shell" / "Dockerfile").read_text()
    assert _arg(text, "OMNICTL_VERSION") == _arg(infra, "OMNICTL_VERSION")


def test_side_by_side_install_layout(text):
    assert "/opt/talosctl/" in text
    assert "/opt/kubectl/" in text
    assert "use-versions" in text


def test_downloads_are_checksum_verified(text):
    assert "sha256sum" in text


def test_autoupdater_disabled(text):
    assert re.search(r"^ENV\b[^\n]*DISABLE_AUTOUPDATER=1", text, re.M) or \
        re.search(r"^\s+DISABLE_AUTOUPDATER=1", text, re.M)


def test_final_user_is_non_root(text):
    users = re.findall(r"^USER\s+(\S+)", text, re.M)
    assert users and users[-1] not in {"root", "0"}


def test_no_claude_install_and_no_skill_md_reliance(text):
    # `claude install` buffers its download ~17x in anon memory (frank gotcha).
    assert "claude install" not in text
    assert "SKILL.md" not in text


def test_nothing_baked_that_needs_runtime_writes(text):
    # Read-only root FS: no VOLUME, and the working dir lives under HOME (an
    # emptyDir at runtime). Home itself is hidden by that mount, so nothing may
    # be baked there either.
    assert not re.search(r"^VOLUME\b", text, re.M)
    assert not re.search(r"^(COPY|ADD)\b[^\n]*/home/", text, re.M)


def test_no_secrets_baked(text):
    assert not re.search(r"(TOKEN|SECRET|PASSWORD|API_KEY)\s*=", text)


@pytest.mark.parametrize("name", [f"TALOSCTL_{_slug(m)}_VERSION" for m in TALOS_MINORS]
                         + [f"KUBECTL_{_slug(m)}_VERSION" for m in K8S_MINORS])
def test_pins_are_registered_in_the_audit(name):
    assert name in PIN_SPECS
