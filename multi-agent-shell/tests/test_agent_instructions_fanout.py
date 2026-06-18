"""Tests for the baked agent-instructions fan-out (cont-init.d/46-agent-instructions
+ link-agent-instructions.sh).

A deployment provides ONE canonical $HOME/AGENTS.md; the image symlinks the
per-harness filenames to it so whichever harness the driver launches loads the same
instructions. AGENTS.md-native harnesses (codex/opencode/antigravity/pi) need no
symlink; claude (CLAUDE.md) and Copilot (.github/copilot-instructions.md) do.
Idempotent, fail-open, never clobbers a real mounted file.
"""
import os
import subprocess
from pathlib import Path

MAS = Path(__file__).resolve().parents[1]
HELPER = MAS / "rootfs/usr/local/lib/multi-agent-shell/link-agent-instructions.sh"
CONT_INIT = MAS / "rootfs/etc/cont-init.d/46-agent-instructions"


def _run(home, env_extra=None):
    env = dict(os.environ); env["HOME"] = str(home)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["bash", str(HELPER)], capture_output=True, text=True, env=env, timeout=20)


# --- structure ----------------------------------------------------------------

def test_cont_init_execs_helper():
    text = CONT_INIT.read_text()
    assert text.startswith("#!/command/with-contenv bash")
    assert "link-agent-instructions.sh" in text
    assert os.access(CONT_INIT, os.X_OK), "cont-init must be executable"

def test_helper_drops_gemini_and_targets_claude_copilot():
    text = HELPER.read_text()
    assert "CLAUDE.md" in text and "copilot-instructions.md" in text
    assert "GEMINI.md" not in text, "antigravity reads AGENTS.md; no GEMINI.md symlink"


# --- functional ---------------------------------------------------------------

def test_fans_out_to_claude_and_copilot(tmp_path):
    home = tmp_path; (home / "AGENTS.md").write_text("# instructions\n")
    r = _run(home); assert r.returncode == 0, r.stderr
    claude = home / "CLAUDE.md"
    copilot = home / ".github/copilot-instructions.md"
    assert claude.is_symlink() and os.readlink(claude) == "AGENTS.md"
    assert copilot.is_symlink() and os.readlink(copilot) == "../AGENTS.md"
    # both resolve to the canonical content
    assert claude.read_text() == "# instructions\n"
    assert copilot.read_text() == "# instructions\n"

def test_no_source_is_noop(tmp_path):
    r = _run(tmp_path); assert r.returncode == 0
    assert not (tmp_path / "CLAUDE.md").exists(), "no AGENTS.md → no symlinks"
    assert "nothing to fan out" in r.stdout

def test_never_clobbers_a_real_mounted_file(tmp_path):
    home = tmp_path; (home / "AGENTS.md").write_text("canonical\n")
    (home / "CLAUDE.md").write_text("a directly-mounted CLAUDE.md\n")   # real file, not a symlink
    r = _run(home); assert r.returncode == 0
    assert not (home / "CLAUDE.md").is_symlink(), "must not clobber a mounted CLAUDE.md"
    assert (home / "CLAUDE.md").read_text() == "a directly-mounted CLAUDE.md\n"
    assert (home / ".github/copilot-instructions.md").is_symlink()     # the others still linked

def test_idempotent(tmp_path):
    home = tmp_path; (home / "AGENTS.md").write_text("x\n")
    assert _run(home).returncode == 0
    r = _run(home); assert r.returncode == 0                            # second run, no error
    assert (home / "CLAUDE.md").is_symlink()

def test_link_list_is_configurable(tmp_path):
    home = tmp_path; (home / "AGENTS.md").write_text("x\n")
    r = _run(home, {"AGENT_INSTRUCTION_LINKS": "PI.md=AGENTS.md"})
    assert r.returncode == 0
    assert (home / "PI.md").is_symlink() and os.readlink(home / "PI.md") == "AGENTS.md"
