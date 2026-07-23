"""Guard: upstream resolution, and the two pins whose target is NOT "latest".

These tests are hermetic - every network call goes through an injected fetch, so
the suite runs offline and in CI without reaching a registry.

The important cases here are the ones that bit during the 2026-07-23 manual
sweep:
  * tmux-resurrect / tmux-continuum publish TAGS but no releases, so a
    releases-only lookup 404s on both.
  * talosctl and omnictl must NOT resolve to the newest upstream release. Their
    target is live infrastructure, and when that can't be probed the honest
    answer is "unknown" - pinning to latest would re-create the skew in the
    opposite direction.
"""
import pytest

from version_audit import (
    Pin,
    resolve_latest,
    resolve_target,
)


def fake_fetch(responses):
    """Build a fetch(url) that serves recorded payloads and 404s otherwise."""
    def _fetch(url):
        for fragment, payload in responses.items():
            if fragment in url:
                if payload is None:
                    raise FileNotFoundError(url)  # stands in for a 404
                return payload
        raise FileNotFoundError(url)
    return _fetch


# --- per-source resolution -------------------------------------------------


def test_npm_resolution():
    pin = Pin(name="CODEX_VERSION", current="0.136.0", source="npm",
              source_ref="@openai/codex")
    fetch = fake_fetch({"registry.npmjs.org": {"version": "0.145.0"}})
    assert resolve_latest(pin, fetch=fetch) == "0.145.0"


def test_pypi_resolution():
    pin = Pin(name="HINDSIGHT_API_VERSION", current="0.8.4", source="pypi",
              source_ref="hindsight-api")
    fetch = fake_fetch({"pypi.org": {"info": {"version": "0.8.5"}}})
    assert resolve_latest(pin, fetch=fetch) == "0.8.5"


def test_github_release_resolution():
    pin = Pin(name="SUPERCRONIC_VERSION", current="0.2.33",
              source="github-release", source_ref="aptible/supercronic")
    fetch = fake_fetch({"releases/latest": {"tag_name": "v0.2.47"}})
    assert resolve_latest(pin, fetch=fetch) == "v0.2.47"


def test_github_release_falls_back_to_tags_on_404():
    """tmux-resurrect and tmux-continuum have tags but no releases. A
    releases-only resolver reports 'unknown' for two perfectly current pins."""
    pin = Pin(name="TMUX_RESURRECT_REF", current="v4.0.0",
              source="github-release", source_ref="tmux-plugins/tmux-resurrect")
    fetch = fake_fetch({
        "releases/latest": None,            # 404, as upstream really does
        "/tags": [{"name": "v4.0.0"}, {"name": "v3.0.0"}],
    })
    assert resolve_latest(pin, fetch=fetch) == "v4.0.0"


def test_github_tag_source_goes_straight_to_tags():
    pin = Pin(name="TMUX_CONTINUUM_REF", current="v3.1.0",
              source="github-tag", source_ref="tmux-plugins/tmux-continuum")
    fetch = fake_fetch({"/tags": [{"name": "v3.1.0"}]})
    assert resolve_latest(pin, fetch=fetch) == "v3.1.0"


def test_dockerhub_resolution_skips_floating_tags():
    """`latest` and `main` move; pinning to them defeats the point of a pin."""
    pin = Pin(name="HERMES_TAG", current="v2026.7.7.2", source="dockerhub",
              source_ref="nousresearch/hermes-agent")
    fetch = fake_fetch({"hub.docker.com": {"results": [
        {"name": "latest", "last_updated": "2026-07-23"},
        {"name": "main", "last_updated": "2026-07-23"},
        {"name": "v2026.7.20", "last_updated": "2026-07-20"},
        {"name": "v2026.7.7.2", "last_updated": "2026-07-08"},
    ]}})
    assert resolve_latest(pin, fetch=fetch) == "v2026.7.20"


def test_source_none_resolves_to_none():
    """NODE_MAJOR and the frozen anchors have no upstream to query."""
    pin = Pin(name="NODE_MAJOR", current="22", source="none")
    assert resolve_latest(pin, fetch=fake_fetch({})) is None


def test_unreachable_upstream_is_unknown_not_a_crash():
    pin = Pin(name="SUPERCRONIC_VERSION", current="0.2.33",
              source="github-release", source_ref="aptible/supercronic")
    assert resolve_latest(pin, fetch=fake_fetch({})) is None


# --- the anchored pins -----------------------------------------------------


def test_talosctl_target_is_the_cluster_not_latest():
    """The whole reason this script exists. Cluster v1.12.6 while upstream is at
    v1.13.7 - the correct pin is the cluster's, not the newest release."""
    pin = Pin(name="TALOSCTL_VERSION", current="v1.9.5",
              source="github-release", source_ref="siderolabs/talos",
              anchor="cluster")
    target = resolve_target(pin, probes={"cluster": lambda: "v1.12.6"})
    assert target == "v1.12.6"


def test_omnictl_target_is_the_server_not_latest():
    pin = Pin(name="OMNICTL_VERSION", current="v0.45.1",
              source="github-release", source_ref="siderolabs/omni",
              anchor="omni-server")
    target = resolve_target(pin, probes={"omni-server": lambda: "v1.5.0"})
    assert target == "v1.5.0"


@pytest.mark.parametrize("anchor", ["cluster", "omni-server"])
def test_unreachable_anchor_reports_unknown_never_falls_back_to_latest(anchor):
    """A confident wrong answer is worse than an honest gap: a guessed omnictl
    is the client for the one control plane you need during a recovery."""
    def boom():
        raise RuntimeError("unreachable")

    pin = Pin(name="X", current="v0.1.0", source="github-release",
              source_ref="o/r", anchor=anchor)
    assert resolve_target(pin, probes={anchor: boom}) is None


def test_unanchored_pin_targets_upstream_latest():
    pin = Pin(name="SUPERCRONIC_VERSION", current="0.2.33",
              source="github-release", source_ref="aptible/supercronic")
    fetch = fake_fetch({"releases/latest": {"tag_name": "v0.2.47"}})
    assert resolve_target(pin, probes={}, fetch=fetch) == "v0.2.47"
