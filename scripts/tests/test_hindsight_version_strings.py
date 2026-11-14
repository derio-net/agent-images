"""Guard: every hindsight-api-slim version string matches the Dockerfile ARG (#170).

The README, the Dockerfile comment and the hindsight-api run script each name
the pinned hindsight-api-slim version; they drifted from the ARG (0.8.4 vs
0.8.5). The ARG is the source of truth.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE = REPO_ROOT / "hermes-agent-shell-hindsight"
DOCKERFILE = IMAGE / "Dockerfile"

ARG_RE = re.compile(r"ARG HINDSIGHT_API_VERSION=(\S+)")
VERSION_RE = re.compile(r"hindsight-api-slim(\[[^\]]*\])?(==|\s+)(\d+\.\d+\.\d+)")
FILES = [
    IMAGE / "README.md",
    DOCKERFILE,
    IMAGE / "rootfs/etc/services.d/hindsight-api/run",
]


def test_dockerfile_declares_api_version():
    assert ARG_RE.search(DOCKERFILE.read_text())


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_version_strings_match_arg(path):
    pinned = ARG_RE.search(DOCKERFILE.read_text()).group(1)
    found = [m.group(3) for m in VERSION_RE.finditer(path.read_text())]
    assert found, f"{path} names no hindsight-api-slim version"
    assert set(found) == {pinned}, f"{path}: {found} != ARG {pinned}"
