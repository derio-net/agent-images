"""hindsight-api identity check (agent-images#170).

Before exec'ing hindsight-api, `run` compares the system identifier of OUR
PGDATA (pg_controldata) with the one the server on 127.0.0.1:5433 reports. A
foreign postgres on that port (frank's ssh-sidecar) answers pg_isready too.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN = (REPO_ROOT / "hermes-agent-shell-hindsight"
       / "rootfs/etc/services.d/hindsight-api/run")


def _exe(path, text):
    path.write_text(text)
    path.chmod(0o755)


def _drive(tmp_path, *, psql_out="111", psql_rc=0, ctl_id="111", ctl_rc=0, psql_err=""):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    rec = tmp_path / "rec"
    rec.mkdir()
    _exe(stubs / "pg_isready", "#!/bin/sh\nexit 0\n")
    _exe(stubs / "psql",
         f'#!/bin/sh\necho "$@" > "{rec}/psql_argv"\n'
         f'echo "PGCONNECT_TIMEOUT=$PGCONNECT_TIMEOUT" > "{rec}/psql_env"\n'
         f'printf "%s" "$PSQL_ERR" >&2\nprintf "%s" "$PSQL_OUT"\nexit "$PSQL_RC"\n')
    _exe(stubs / "pg_controldata",
         '#!/bin/sh\necho "Database system identifier:           $CTL_ID"\n'
         'exit "$CTL_RC"\n')
    _exe(stubs / "micromamba", f'#!/bin/sh\necho "$@" > "{rec}/micromamba"\n')
    _exe(tmp_path / "halt", f'#!/bin/sh\necho "$@" > "{rec}/halt"\n')
    env = {**os.environ,
           "PATH": f"{stubs}:{os.environ['PATH']}",
           "HINDSIGHT_PG_BIN": str(stubs),
           "HINDSIGHT_HALT": str(tmp_path / "halt"),
           "HINDSIGHT_PGDATA": str(tmp_path / "pgdata"),
           "PSQL_OUT": psql_out, "PSQL_RC": str(psql_rc), "PSQL_ERR": psql_err,
           "CTL_ID": ctl_id, "CTL_RC": str(ctl_rc)}
    p = subprocess.run(["bash", str(RUN)], env=env, capture_output=True,
                       text=True, timeout=30)
    return p, rec


def test_matching_ids_exec_hindsight_api(tmp_path):
    p, rec = _drive(tmp_path)
    assert p.returncode == 0
    assert "hindsight-api" in (rec / "micromamba").read_text()
    assert not (rec / "halt").exists()


def test_mismatch_halts_with_both_ids(tmp_path):
    p, rec = _drive(tmp_path, psql_out="999", ctl_id="111")
    assert p.returncode == 1
    halt = (rec / "halt").read_text()
    assert halt.split()[0] == "1"
    assert "999" in halt and "111" in halt
    assert not (rec / "micromamba").exists()


@pytest.mark.parametrize("kw", [
    {"psql_rc": 2},
    {"psql_out": ""},
    {"ctl_rc": 1},
    {"ctl_id": ""},  # pg_controldata exits 0 but yields no identifier
])
def test_unreadable_halts_and_never_execs(tmp_path, kw):
    p, rec = _drive(tmp_path, **kw)
    assert p.returncode == 1
    assert (rec / "halt").read_text().split()[0] == "1"
    assert not (rec / "micromamba").exists()


def test_psql_is_non_interactive_and_bounded(tmp_path):
    _, rec = _drive(tmp_path)
    argv = (rec / "psql_argv").read_text().split()
    assert "-X" in argv and "-w" in argv
    assert "PGCONNECT_TIMEOUT=" in (rec / "psql_env").read_text()
    assert (rec / "psql_env").read_text().strip() != "PGCONNECT_TIMEOUT="


def test_unreadable_reason_carries_the_tool_stderr(tmp_path):
    p, rec = _drive(tmp_path, psql_rc=2, psql_err="FATAL: password authentication failed")
    assert "password authentication failed" in (rec / "halt").read_text()
