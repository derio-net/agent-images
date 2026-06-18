"""Tests for the baked native-harness installer (cont-init.d/45-native-harnesses
+ install-native-harness.sh).

The image bakes the memory-safe native claude install: plain `curl` of the
published binary into the PV-resident $HOME/.local (NOT `claude install`, which
buffers ~4GiB and OOM-kills a memory-limited pod). It must be idempotent (skip the
~232MB download when already current) and fail-open (never block container boot).
Functional tests drive the helper with PATH-injected fake curl/jq/sha256sum.
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

MAS = Path(__file__).resolve().parents[1]
HELPER = MAS / "rootfs/usr/local/lib/multi-agent-shell/install-native-harness.sh"
CONT_INIT = MAS / "rootfs/etc/cont-init.d/45-native-harnesses"

FAKE_CURL = r'''#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_LOG"
url="${@: -1}"                       # the URL is the last argument
out=""; prev=""; for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
[ "${FAKE_CURL_FAIL:-0}" = 1 ] && exit 22
case "$url" in
  */latest)        printf '%s' "${FAKE_VERSION:-9.9.9}" ;;
  */manifest.json) printf '%s' '{"platforms":{"linux-x64":{"checksum":"abc123"}}}' ;;
  */linux-x64/claude) printf 'FAKEBINARY' > "$out" ;;
esac
exit 0
'''
FAKE_JQ = "#!/usr/bin/env bash\ncat >/dev/null\nprintf '%s' abc123\n"            # echo the checksum
FAKE_SHA = "#!/usr/bin/env bash\ncat >/dev/null\nexit 0\n"                       # sha256sum -c --status → match


def _harness(tmp_path, *, version="9.9.9", curl_fail=False):
    bindir = tmp_path / "bin"; bindir.mkdir()
    for name, body in (("curl", FAKE_CURL), ("jq", FAKE_JQ), ("sha256sum", FAKE_SHA)):
        f = bindir / name; f.write_text(body); f.chmod(f.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "home"; home.mkdir()
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HOME"] = str(home)
    env["FAKE_LOG"] = str(tmp_path / "curl.log")
    env["FAKE_VERSION"] = version
    if curl_fail:
        env["FAKE_CURL_FAIL"] = "1"
    return env, home

def _run(env):
    return subprocess.run(["bash", str(HELPER), "claude"], capture_output=True, text=True, env=env, timeout=30)

def _curl_log(tmp_path):
    p = tmp_path / "curl.log"
    return p.read_text() if p.exists() else ""


# --- structure ----------------------------------------------------------------

def test_cont_init_execs_the_helper():
    text = CONT_INIT.read_text()
    assert text.startswith("#!/command/with-contenv bash"), "must use the s6 with-contenv shebang"
    assert "install-native-harness.sh" in text and "claude" in text
    assert os.access(CONT_INIT, os.X_OK), "cont-init script must be executable"

def test_helper_is_memory_safe_not_install_subcommand():
    text = HELPER.read_text()
    assert "downloads.claude.ai" in text and "curl" in text, "must curl the published binary"
    # MUST NOT shell out to `claude install` (the OOM path).
    assert "claude install" not in text, "must NOT use `claude install` (buffers ~4GiB → OOM)"
    assert "sha256sum" in text, "must checksum-verify the download"


# --- functional ---------------------------------------------------------------

def test_installs_native_binary_and_symlink(tmp_path):
    env, home = _harness(tmp_path)
    r = _run(env)
    assert r.returncode == 0, r.stderr
    link = home / ".local/bin/claude"
    assert link.is_symlink(), f"must symlink ~/.local/bin/claude; out={r.stdout}"
    assert link.resolve().name == "9.9.9"
    assert (home / ".local/share/claude/versions/9.9.9").exists()
    assert "/linux-x64/claude" in _curl_log(tmp_path), "first install must download the binary"

def test_idempotent_skips_when_current(tmp_path):
    env, home = _harness(tmp_path)
    assert _run(env).returncode == 0           # first install
    (tmp_path / "curl.log").write_text("")     # reset the call log
    r = _run(env)                              # second run, same version
    assert r.returncode == 0
    assert "already installed" in r.stdout
    assert "/linux-x64/claude" not in _curl_log(tmp_path), "must NOT re-download when current"

def test_fail_open_on_network_error(tmp_path):
    env, home = _harness(tmp_path, curl_fail=True)
    r = _run(env)
    assert r.returncode == 0, "must fail-open (never block boot) when the CDN is unreachable"
    assert not (home / ".local/bin/claude").exists(), "no symlink written on failure"
