"""Guard: agent-shell-base must re-set PATH on AGENT_HOME, not leak the base
image's hardcoded /home/claude/.local/bin.

The non-login s6 agent-session driver launches `claude` via tmux with the baked
ENV PATH (the profile.d ~/.local/bin shim applies only to LOGIN shells). If PATH
points at /home/claude/.local/bin (the parent image's default user) instead of
$AGENT_HOME/.local/bin, a non-kali shell (user `agent`, HOME /home/agent) resolves
the npm /usr/bin/claude — whose auto-updater can't write the root-owned npm prefix
("no write permission to npm prefix") — rather than the PV-installed native build
that self-updates. Bug found live on alert-agent 2026-06-18.
"""
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_path_env_is_parameterized_on_agent_home():
    df = DOCKERFILE.read_text()
    assert "PATH=${AGENT_HOME}/.local/bin" in df, \
        "agent-shell-base must re-set PATH=${AGENT_HOME}/.local/bin (else base's /home/claude leaks)"


def test_no_hardcoded_home_claude_in_a_path_line():
    # This image overrides the user, so any PATH it sets must track AGENT_HOME —
    # never a literal /home/claude (that's only correct in the base default).
    for line in DOCKERFILE.read_text().splitlines():
        if "PATH=" in line and not line.strip().startswith("#"):
            assert "/home/claude" not in line, f"hardcoded /home/claude in PATH line: {line.strip()}"
