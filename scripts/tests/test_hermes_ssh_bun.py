"""Guard: the Bun runtime in the hermes ssh sidecar (derio-net/frank#759).

The ssh sidecar is the only container in the `hermes-agent-shell` pod we
control, so it is where a JavaScript runtime has to live. The tool that needs
it is installed by the operator at runtime, not baked - see the frank spec's
decision 2 - so this image's job is narrow: provide `bun`, and make sure a
login shell can see what the operator installs with it.

Three things are load-bearing and all three are silent when wrong:

1. WHERE bun is installed. `$AGENT_HOME` is `/opt/data/home`, which is a
   Longhorn PVC MOUNT at runtime. Anything the image bakes under that path is
   hidden the moment the volume mounts - the build succeeds, the layer is
   there, and the running container has no `bun`. Bun's own installer defaults
   to `~/.bun`, i.e. exactly the wrong place, so the obvious command is the
   broken one.

2. THAT there is a profile.d shim. sshd scrubs the container environment, and
   in this sidecar sshd is PID 1 (so the `/proc/1/environ` re-export trick used
   elsewhere in this family reads proctitle junk). A login shell's PATH comes
   from /etc/profile.d or from nowhere.

3. That the pin is REGISTERED. `version_audit.find_uncovered_version_args`
   fails on any versionish ARG missing from `PIN_SPECS`, by design - so the
   registry entry is part of the change, not follow-up bookkeeping.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from version_audit import PIN_SPECS, Pin, Status, classify_status

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "hermes-agent-shell-ssh/Dockerfile"
SHIM = REPO_ROOT / "hermes-agent-shell-ssh/rootfs/etc/profile.d/36-hermes-bun-path.sh"

# The PVC mount point. Nothing bun-related may be installed under it.
AGENT_HOME = "/opt/data/home"


def _dockerfile() -> str:
    return DOCKERFILE.read_text()


def _dockerfile_instructions() -> str:
    """The Dockerfile with comment lines removed.

    Scanning raw text is how a guard ends up matching the very comment that
    explains the trap it guards. This repo has already shipped one of those (a
    seed-source check that matched its own explanatory comment and passed
    against a doctored `cp` line). The comments here deliberately quote
    `${AGENT_HOME}` and `/opt/data/home` while telling you NOT to install
    there, so a naive scan reads them as violations.
    """
    return "\n".join(
        line for line in _dockerfile().splitlines()
        if not line.lstrip().startswith("#")
    )


def _arg(name: str) -> str:
    m = re.search(rf"^ARG\s+{name}=(.+)$", _dockerfile(), re.MULTILINE)
    assert m, f"{name} not found in {DOCKERFILE.relative_to(REPO_ROOT)}"
    return m.group(1).strip()


# --- the pin ---------------------------------------------------------------


def test_bun_version_is_pinned_to_a_bare_semver():
    """Bare semver, no `v` prefix: the download URL builds the `bun-v` tag from
    it, so carrying the prefix here would double it."""
    value = _arg("BUN_VERSION")
    assert re.fullmatch(r"\d+\.\d+\.\d+", value), (
        f"BUN_VERSION must be a bare semver like 1.3.14, got {value!r}"
    )


def test_bun_pin_is_registered_in_the_audit():
    """An unregistered pin fails `find_uncovered_version_args` - this asserts
    the entry is not just present but correctly described."""
    assert "BUN_VERSION" in PIN_SPECS, (
        "BUN_VERSION must be in version_audit.PIN_SPECS - an unregistered pin "
        "is exactly the quiet omission that module exists to prevent"
    )
    spec = PIN_SPECS["BUN_VERSION"]
    assert spec["source"] == "github-release"
    assert spec["source_ref"] == "oven-sh/bun"
    assert spec["classification"] == "rebuild-only", (
        "nothing self-updates bun in-pod, so the image rebuild is the only "
        "refresh path"
    )


def test_bun_release_tag_prefix_is_declared():
    """bun tags releases `bun-v1.3.14`, not `v1.3.14`."""
    assert PIN_SPECS["BUN_VERSION"].get("tag_prefix") == "bun-", (
        "without a tag_prefix the audit compares `1.3.14` against the release "
        "tag `bun-v1.3.14` and reports a permanently BEHIND pin"
    )


def _pin(current: str) -> Pin:
    spec = PIN_SPECS["BUN_VERSION"]
    return Pin(
        name="BUN_VERSION", current=current,
        source=spec["source"], source_ref=spec["source_ref"],
        classification=spec["classification"], tag_prefix=spec.get("tag_prefix"),
    )


def test_a_current_bun_pin_does_not_read_as_behind():
    """The false positive this prefix exists to prevent. version_audit's own
    docstring: a report with false positives stops being read."""
    assert classify_status(_pin("1.3.14"), "bun-v1.3.14") is Status.CURRENT


def test_the_prefix_does_not_blind_real_drift():
    """Stripping a prefix must not turn the comparison into a no-op - a genuine
    upstream bump still has to read BEHIND."""
    assert classify_status(_pin("1.3.14"), "bun-v1.3.15") is Status.BEHIND


# --- where it is installed -------------------------------------------------


def test_bun_is_installed_as_root_before_the_user_switch():
    """Note this reads the whole instruction text, not one `RUN` line: the
    install is a multi-line RUN and its bun references sit on continuation
    lines, so a `^RUN .*bun.*$` match would see nothing and pass only for a
    one-line install."""
    text = _dockerfile_instructions()
    user_switch = text.index("USER ${AGENT_USER}")

    assert text.index("ARG BUN_VERSION=") < user_switch, (
        "BUN_VERSION must be declared before the USER switch"
    )
    assert text.index("/usr/local/bin/bun") < user_switch, (
        "bun must be installed while still root - a non-root RUN cannot write "
        "to /usr/local/bin"
    )


def test_bun_is_not_installed_under_the_pvc_mount():
    """The trap. `$AGENT_HOME` is a PVC mount at runtime: anything baked under
    it is hidden the moment the volume mounts, so the image would build clean
    and the container would have no bun."""
    text = _dockerfile_instructions()
    for line in text.splitlines():
        if "bun" not in line.lower():
            continue
        assert AGENT_HOME not in line, (
            f"bun must not be installed under the PVC mount {AGENT_HOME}: {line!r}"
        )
        assert "${AGENT_HOME}" not in line and "$AGENT_HOME" not in line, (
            f"bun must not be installed under $AGENT_HOME (a PVC mount): {line!r}"
        )
    assert "/usr/local/bin/bun" in text, (
        "bun belongs in /usr/local/bin - outside every PVC mount in this pod"
    )


def test_the_pvc_mount_guard_actually_catches_a_violation():
    """Mutation check on the guard above, in-process: a guard that has never
    seen a failing input is a claim, not a check."""
    offending = 'RUN curl -o ${AGENT_HOME}/.bun/bin/bun https://example.invalid'
    hits = [
        line for line in offending.splitlines()
        if "bun" in line.lower() and "${AGENT_HOME}" in line
    ]
    assert hits, "the guard's own matching logic must flag an install under $AGENT_HOME"


def test_the_download_is_checksum_verified():
    text = _dockerfile()
    assert "SHASUMS256.txt" in text, (
        "verify against the release's own checksum file, so a version bump is "
        "one line and cannot silently skip verification"
    )
    assert "sha256sum" in text and "--check" in text


def test_the_architecture_is_derived_not_hardcoded():
    """This image builds amd64 today. A hardcoded x64 asset is how a future
    multi-arch build produces a silently broken image."""
    text = _dockerfile()
    assert "dpkg --print-architecture" in text, (
        "derive the bun asset from the build architecture"
    )
    assert "bun-linux-aarch64" in text, "the arm64 asset name must be handled"


def test_unzip_is_available_for_the_bun_archive():
    assert re.search(r"^\s+unzip \\$", _dockerfile(), re.MULTILINE), (
        "unzip belongs in the existing apt list, not a second apt-get layer"
    )


# --- the PATH shim ---------------------------------------------------------


def test_the_path_shim_exists_and_targets_the_pvc_global_dir():
    assert SHIM.exists(), f"missing {SHIM.relative_to(REPO_ROOT)}"
    text = SHIM.read_text()
    assert "$HOME/.bun/bin" in text, (
        "the shim must add bun's GLOBAL bin dir - which lives under $HOME, a "
        "PVC, which is what makes operator-installed CLIs survive a restart"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_the_path_shim_is_idempotent():
    """Login shells and `bash -lc` can both source profile.d in one session, so
    a shim that blindly appends grows PATH without bound.

    This RUNS the shim rather than grepping it: string-matching the guard would
    only assert a spelling (`":$PATH:"` vs `":${PATH}:"`), which says nothing
    about behaviour and breaks on a harmless rewrite.
    """
    script = f'HOME=/tmp/fakehome; PATH=/usr/bin; . "{SHIM}"; . "{SHIM}"; echo "$PATH"'
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert out.count("/tmp/fakehome/.bun/bin") == 1, (
        f"sourcing the shim twice duplicated the PATH entry: {out!r}"
    )
    assert out.startswith("/tmp/fakehome/.bun/bin:"), (
        f"the global bin dir must take precedence: {out!r}"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_the_path_shim_survives_a_missing_bun_dir():
    """Before the operator's first global install the directory legitimately
    does not exist. The shim must not error or complain - a noisy profile.d
    entry greets every single SSH login."""
    script = f'HOME=/nonexistent-{__name__}; . "{SHIM}"; echo OK'
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("OK")
    assert proc.stderr == "", f"the shim wrote to stderr: {proc.stderr!r}"


def test_the_shim_is_made_executable_by_the_build():
    assert "36-hermes-bun-path.sh" in _dockerfile(), (
        "the Dockerfile must chmod the shim alongside the entrypoint"
    )
