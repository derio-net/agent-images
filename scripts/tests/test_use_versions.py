"""Behaviour of the upgrade-session version selector and entrypoint."""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN = REPO_ROOT / "upgrade-session" / "rootfs" / "usr" / "local" / "bin"
USE = BIN / "use-versions"
ENTRY = BIN / "upgrade-session-entrypoint"


@pytest.fixture
def tree(tmp_path):
    tools = tmp_path / "opt"
    for tool, minors in (("talosctl", ["1.12", "1.13", "1.14"]),
                         ("kubectl", ["1.34", "1.35", "1.36", "1.37"])):
        for m in minors:
            p = tools / tool / m / tool
            p.parent.mkdir(parents=True)
            p.write_text(f"#!/bin/sh\necho {tool} {m}\n")
            p.chmod(0o755)
    return tmp_path


def run(script, tree, *args, env=None):
    e = {"PATH": os.environ["PATH"],
         "UPGRADE_TOOLS_ROOT": str(tree / "opt"),
         "UPGRADE_BIN_DIR": str(tree / "bin")}
    e.update(env or {})
    return subprocess.run([str(script), *args], env=e, capture_output=True, text=True)


def target(tree, tool):
    return os.readlink(tree / "bin" / tool)


def test_flags_link_selected_minors(tree):
    r = run(USE, tree, "--talos", "1.13", "--kubernetes", "1.36")
    assert r.returncode == 0, r.stderr
    assert target(tree, "talosctl").endswith("/talosctl/1.13/talosctl")
    assert target(tree, "kubectl").endswith("/kubectl/1.36/kubectl")


def test_env_vars_select_when_no_flags(tree):
    r = run(USE, tree, env={"UPGRADE_TALOS_MINOR": "1.14", "UPGRADE_K8S_MINOR": "1.37"})
    assert r.returncode == 0, r.stderr
    assert target(tree, "talosctl").endswith("/talosctl/1.14/talosctl")
    assert target(tree, "kubectl").endswith("/kubectl/1.37/kubectl")


def test_flag_overrides_env(tree):
    r = run(USE, tree, "--talos", "1.12", env={"UPGRADE_TALOS_MINOR": "1.14"})
    assert r.returncode == 0
    assert target(tree, "talosctl").endswith("/talosctl/1.12/talosctl")


def test_unknown_minor_exits_2_and_links_nothing(tree):
    r = run(USE, tree, "--talos", "1.99", "--kubernetes", "1.36")
    assert r.returncode == 2
    assert "1.99" in r.stderr and "1.12" in r.stderr  # names what is available
    assert not (tree / "bin" / "kubectl").exists()  # all-or-nothing


def test_rerun_switches_the_link(tree):
    run(USE, tree, "--talos", "1.12")
    run(USE, tree, "--talos", "1.13")
    assert target(tree, "talosctl").endswith("/talosctl/1.13/talosctl")


def test_only_one_tool_selected_leaves_the_other_alone(tree):
    run(USE, tree, "--kubernetes", "1.34")
    assert not (tree / "bin" / "talosctl").exists()


def test_list_prints_available_minors(tree):
    r = run(USE, tree, "--list")
    assert r.returncode == 0
    assert "talosctl: 1.12 1.13 1.14" in r.stdout
    assert "kubectl: 1.34 1.35 1.36 1.37" in r.stdout


def test_path_resolves_selected_binary(tree):
    run(USE, tree, "--talos", "1.13")
    r = subprocess.run(["talosctl"], capture_output=True, text=True,
                       env={"PATH": f"{tree / 'bin'}:{os.environ['PATH']}"})
    assert r.stdout.strip() == "talosctl 1.13"


def test_entrypoint_applies_env_then_execs_argv(tree):
    r = run(ENTRY, tree, "sh", "-c", "echo hello",
            env={"UPGRADE_TALOS_MINOR": "1.13"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "hello"
    assert target(tree, "talosctl").endswith("/talosctl/1.13/talosctl")


def test_entrypoint_with_no_env_still_execs(tree):
    r = run(ENTRY, tree, "sh", "-c", "echo hi")
    assert r.returncode == 0 and r.stdout.strip() == "hi"


def test_entrypoint_fails_loudly_on_bad_minor(tree):
    r = run(ENTRY, tree, "sh", "-c", "echo should-not-run",
            env={"UPGRADE_K8S_MINOR": "9.9"})
    assert r.returncode == 2
    assert "should-not-run" not in r.stdout
