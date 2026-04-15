#!/usr/bin/env python3
"""guardrails-hook.py — Willikins agent security guardrails.

Claude Code hook script: blocks dangerous operations (PreToolUse)
and logs all bash commands (PostToolUse).

Exit codes:
  0 — allow the operation
  2 — block the operation (message on stderr)

Hook input: JSON on stdin with keys: hook_type, tool_name, tool_input, session_id
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALLOWED_GIT_REMOTE = "github.com/derio-net/"
SAFE_WRITE_PREFIX = "/home/claude/repos/"
AUDIT_LOG = os.path.expanduser("~/.willikins-agent/audit.jsonl")
NOTIFY_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notify-telegram.sh")

# ---------------------------------------------------------------------------
# PreToolUse Bash block rules
# ---------------------------------------------------------------------------

BASH_BLOCK_RULES = [
    (
        "DESTROY_FS",
        r"rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)*(/(?:\s|$)|~(?:\s|$)|\.(?:\s|$))",
        "Blocked: recursive deletion of root, home, or cwd",
    ),
    (
        "FORCE_PUSH_PROTECTED",
        r"git\s+push\s+.*--force.*\b(main|master)\b",
        "Blocked: force push to protected branch",
    ),
    (
        "PUSH_FOREIGN_REMOTE",
        None,  # Custom check — see _check_push_foreign
        "Blocked: git push to non-approved remote",
    ),
    (
        "EXFIL_SECRETS",
        r"(curl|wget|nc)\s.*\$\{?\w*(KEY|TOKEN|PASSWORD|SECRET)",
        "Blocked: suspected credential exfiltration",
    ),
    (
        "COMMIT_SECRETS",
        r"git\s+add\s+.*\.(env|key|pem|p12)\b",
        "Blocked: staging credential files",
    ),
    (
        "NUKE_K8S",
        r"kubectl\s+delete\s+(namespace|ns)\s",
        "Blocked: namespace-level deletion",
    ),
    (
        "NUKE_TALOS",
        r"talosctl\s+(reset|upgrade)(\s+(?!.*--preserve)\S.*|$)",
        "Blocked: destructive Talos operation (use --preserve)",
    ),
    (
        "DOWNLOAD_EXEC",
        r"(curl|wget)\s+.*\|\s*(ba)?sh",
        "Blocked: download-and-execute pattern",
    ),
    (
        "SUDO_ATTEMPT",
        r"sudo\s+",
        "Blocked: sudo not permitted on this pod",
    ),
]

SYSTEM_PREFIXES = ("/etc/", "/usr/", "/bin/", "/sbin/")
CREDENTIAL_EXTENSIONS = (".env", ".key", ".pem", ".p12")


def _check_push_foreign(command: str) -> bool:
    """Return True if `git push` targets a non-approved remote."""
    if not re.search(r"git\s+push\b", command):
        return False
    # Allow pushes that don't specify a URL (use configured remote)
    # Block pushes with explicit URLs not matching ALLOWED_GIT_REMOTE
    url_match = re.search(r"git\s+push\s+(https?://\S+|git@\S+)", command)
    if url_match:
        url = url_match.group(1)
        return ALLOWED_GIT_REMOTE not in url
    # No explicit URL — check if "origin" or no remote specified (allowed)
    # Block if a named remote other than "origin" is used (conservative)
    parts = re.split(r"\s+", command)
    try:
        push_idx = parts.index("push")
        # Next non-flag arg after "push" is the remote name
        for arg in parts[push_idx + 1 :]:
            if arg.startswith("-"):
                continue
            # Known safe remote names
            if arg in ("origin",):
                return False
            # Unknown remote name — block
            return True
    except (ValueError, IndexError):
        pass
    return False


def check_pretooluse_bash(command: str) -> None:
    """Block dangerous bash commands. Raises SystemExit(2) on block."""
    for rule_id, pattern, message in BASH_BLOCK_RULES:
        if rule_id == "PUSH_FOREIGN_REMOTE":
            if _check_push_foreign(command):
                _block(rule_id, message)
        elif pattern and re.search(pattern, command):
            _block(rule_id, message)


def check_pretooluse_write(tool_name: str, tool_input: dict) -> None:
    """Block writes to protected paths. Raises SystemExit(2) on block."""
    file_path = tool_input.get("file_path", "")

    if file_path.startswith("/run/secrets/"):
        _block("WRITE_SECRETS_DIR", "Blocked: secrets volume is read-only")

    for prefix in SYSTEM_PREFIXES:
        if file_path.startswith(prefix):
            _block("WRITE_SYSTEM", f"Blocked: cannot write to {prefix}")

    # Credential files outside repos
    if any(file_path.endswith(ext) for ext in CREDENTIAL_EXTENSIONS):
        if not file_path.startswith(SAFE_WRITE_PREFIX):
            _block("WRITE_CREDENTIAL_FILE", "Blocked: credential file outside repos/")


# ---------------------------------------------------------------------------
# PostToolUse — Audit logging + alerts
# ---------------------------------------------------------------------------

def handle_posttooluse(data: dict) -> None:
    """Log bash commands to audit.jsonl and alert on git push."""
    if data.get("tool_name") != "Bash":
        return

    command = data.get("tool_input", {}).get("command", "")
    exit_code = data.get("tool_output", {}).get("exit_code", None)
    session_id = data.get("session_id", "unknown")

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session": session_id,
        "command": command,
        "exit_code": exit_code,
    }

    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Alert on git push
    if re.search(r"git\s+push\b", command) and exit_code == 0:
        _telegram_notify(f"🔔 *Willikins pushed code*\n`{command}`")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block(rule_id: str, message: str) -> None:
    """Print block message and exit with code 2."""
    print(json.dumps({"rule": rule_id, "message": message}), file=sys.stderr)
    sys.exit(2)


def _telegram_notify(text: str) -> None:
    """Best-effort Telegram notification. Failures are logged, not raised."""
    if not os.path.isfile(NOTIFY_SCRIPT):
        return
    try:
        import subprocess
        subprocess.run(
            [NOTIFY_SCRIPT, text],
            timeout=10,
            capture_output=True,
        )
    except Exception:
        pass  # Best effort — don't block Claude on notification failure


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    data = json.loads(raw)
    hook_type = data.get("hook_type", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if hook_type == "PreToolUse":
        if tool_name == "Bash":
            check_pretooluse_bash(tool_input.get("command", ""))
        elif tool_name in ("Write", "Edit"):
            check_pretooluse_write(tool_name, tool_input)

    elif hook_type == "PostToolUse":
        handle_posttooluse(data)

    sys.exit(0)


if __name__ == "__main__":
    main()
