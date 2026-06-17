"""Guard: tmux-continuum auto-restore must be GATED on AGENT_TMUX_RESTORE.

continuum auto-restores saved sessions on every fresh tmux-server start. For a
driver-managed agent pod that restores a DEAD bash shell which `ensure_session`
then reuses (the alert-agent DM-into-bash failure). Agent pods (alert-agent,
n8n-01) set AGENT_TMUX_RESTORE=off so continuum never restores; human shells
leave it unset → restore stays on (default). Fix C is the load-bearing guarantee;
this gate is defence + cleanliness.
"""
from pathlib import Path

CONF = Path(__file__).resolve().parents[1] / "etc/agent/tmux-resurrect.conf"


def test_continuum_restore_is_gated_on_env():
    text = CONF.read_text()
    assert "if-shell" in text, "continuum-restore must be gated via if-shell"
    assert "AGENT_TMUX_RESTORE" in text, "gate must read AGENT_TMUX_RESTORE"
    assert "@continuum-restore 'off'" in text, "must turn restore OFF when AGENT_TMUX_RESTORE=off"
    assert "@continuum-restore 'on'" in text, "must keep restore ON otherwise"
    assert "AGENT_TMUX_RESTORE:-on" in text, "must DEFAULT to on when the env is unset"


def test_no_unconditional_restore_on():
    # The old static always-on setter must be gone — only the if-shell branch
    # (a double-quoted argument) may set it on.
    lines = [l.strip() for l in CONF.read_text().splitlines()]
    assert "set -g @continuum-restore 'on'" not in lines, \
        "the unconditional always-on setter must be replaced by the if-shell gate"


def test_gate_precedes_continuum_plugin():
    text = CONF.read_text()
    assert text.index("AGENT_TMUX_RESTORE") < text.index("continuum.tmux"), \
        "the gate must be set BEFORE continuum.tmux runs (plugin reads it at server start)"
