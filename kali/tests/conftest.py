"""Test scaffolding for the vk-issue-bridge suite.

The bridge now invokes `vk.bridge.discover_plans` + `tick` from within
`main()`. That path walks `~/repos/*` and hits the GitHub CLI, which can
hang in CI. The legacy `test_vk_issue_bridge.py` suite mocks the legacy
I/O (`gh_list_ready_issues`, `sync_issue`, …) but was never wired to
mock the new path — and we want it to stay that way (the additive
refactor must not require legacy test changes). This autouse fixture
sets `VK_BRIDGE_SKIP_LIB_PATH=1` for every test by default; opt out with
the `no_stub_vk_bridge` marker (used in `test_vk_bridge_integration.py`'s
delineation test).
"""
from __future__ import annotations

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "no_stub_vk_bridge: do not auto-skip the v2-plan code path",
    )


@pytest.fixture(autouse=True)
def _skip_vk_bridge_lib_path(request, monkeypatch):
    if "no_stub_vk_bridge" in request.keywords:
        return
    monkeypatch.setenv("VK_BRIDGE_SKIP_LIB_PATH", "1")
