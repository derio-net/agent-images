"""Guard: the report ranks by what matters and is honest about what it can't see.

The report exists to answer "what has drifted, and which of it is worth acting
on". Ranking by release count would put a 9-release bootstrap gap (which
self-heals on first boot) above a 3-minor talosctl skew (which is an actual
correctness bug), so the classification split is what it groups by.
"""
from version_audit import Pin, Status, classify_status, render_report


def test_status_behind_when_target_differs():
    pin = Pin(name="SUPERCRONIC_VERSION", current="0.2.33", source="github-release")
    assert classify_status(pin, target="v0.2.47") is Status.BEHIND


def test_status_current_ignores_a_leading_v():
    """Pins are written inconsistently (0.2.33 vs v0.2.47). A pin that only
    LOOKS behind because of a `v` would send someone chasing a no-op bump."""
    pin = Pin(name="SUPERCRONIC_VERSION", current="0.2.47", source="github-release")
    assert classify_status(pin, target="v0.2.47") is Status.CURRENT


def test_status_unknown_when_target_could_not_be_resolved():
    pin = Pin(name="OMNICTL_VERSION", current="v0.45.1", anchor="omni-server")
    assert classify_status(pin, target=None) is Status.UNKNOWN


def test_frozen_pins_are_never_reported_as_behind():
    """BGE_REVISION and RUFLO_ENV_FALLBACK_SHA are deliberate anchors, not
    stale pins - reporting them as drift invites someone to 'fix' them."""
    pin = Pin(name="BGE_REVISION", current="5c38ec7c", frozen=True)
    assert classify_status(pin, target="deadbeef") is Status.FROZEN


def test_unpinned_is_its_own_status():
    pin = Pin(name="@anthropic-ai/claude-code", current=None, unpinned=True)
    assert classify_status(pin, target="2.1.218") is Status.UNPINNED


def test_report_groups_by_classification_and_shows_both_versions():
    pins = [
        Pin(name="TALOSCTL_VERSION", current="v1.9.5", classification="rebuild-only",
            anchor="cluster"),
        Pin(name="CODEX_VERSION", current="0.136.0", classification="bootstrap"),
    ]
    text = render_report(pins, targets={"TALOSCTL_VERSION": "v1.12.6",
                                        "CODEX_VERSION": "0.145.0"})
    assert "rebuild-only" in text and "bootstrap" in text
    assert "v1.9.5" in text and "v1.12.6" in text
    # The anchor must be visible: a reader who doesn't know talosctl tracks the
    # cluster will "helpfully" bump it to latest.
    assert "cluster" in text


def test_report_is_a_report_not_a_gate():
    """Exit 0 even with drift - this is run on demand by a human, and a
    non-zero exit invites someone to wire it into CI as a blocking check."""
    pins = [Pin(name="X", current="1.0.0", classification="rebuild-only")]
    text, exit_code = render_report(pins, targets={"X": "2.0.0"}, with_exit_code=True)
    assert exit_code == 0
    assert "X" in text


def test_packaging_revision_suffix_is_not_drift():
    """Found by the first live run: micromamba pins `2.8.1` but publishes its
    release as `2.8.1-0` - the `-0` is a packaging revision, not a new version.
    Reported as BEHIND it sends someone to bump a pin that is already current,
    and a report with false positives stops being read.
    """
    pin = Pin(name="MICROMAMBA_VERSION", current="2.8.1", source="github-release")
    assert classify_status(pin, target="2.8.1-0") is Status.CURRENT


def test_a_real_prerelease_suffix_is_still_drift():
    """Narrow the fix: only a trailing -<digits> packaging revision is ignored.
    An alphanumeric prerelease is a genuinely different version."""
    pin = Pin(name="X", current="1.0.0", source="github-release")
    assert classify_status(pin, target="1.0.0-rc1") is Status.BEHIND
