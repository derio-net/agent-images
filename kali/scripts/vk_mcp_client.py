"""MCP JSON-RPC client for VibeKanban.

Spawns `npx vibe-kanban@latest --mcp` as a subprocess and communicates
via JSON-RPC 2.0 over stdin/stdout.

Design: `_send` and `_recv` are separate methods that tests can override
via a FakeVkMcpClient subclass, avoiding subprocess mocking entirely.
"""

import json
import queue
import subprocess
import threading
from typing import Any


class VkMcpError(Exception):
    """Raised when the MCP server returns a JSON-RPC error response."""
    pass


class VkMcpClient:
    """MCP client that talks JSON-RPC 2.0 to the VibeKanban MCP server."""

    DEFAULT_COMMAND = ["vibe-kanban-mcp", "--mode", "global"]
    FALLBACK_COMMAND = ["npx", "-y", "vibe-kanban@latest", "--mcp"]

    @classmethod
    def _resolve_command(cls) -> list[str]:
        """Use local binary if available, fall back to npx."""
        import shutil
        if shutil.which(cls.DEFAULT_COMMAND[0]):
            return cls.DEFAULT_COMMAND
        return cls.FALLBACK_COMMAND

    def __init__(self, command: list[str] | None = None):
        self._msg_id = 0
        cmd = command or self._resolve_command()
        env = {**subprocess.os.environ}
        if "VIBE_BACKEND_URL" not in env:
            env["VIBE_BACKEND_URL"] = "http://localhost:8081"
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._recv_queue: queue.Queue[dict] = queue.Queue()
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True
        )
        self._reader_thread.start()
        self._initialize()

    def _read_loop(self):
        """Read JSON-RPC messages from subprocess stdout into a queue."""
        assert self._process.stdout is not None
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                self._recv_queue.put(msg)
            except json.JSONDecodeError:
                continue

    def _send(self, msg: dict):
        """Send a JSON-RPC message to the subprocess stdin."""
        assert self._process.stdin is not None
        data = json.dumps(msg) + "\n"
        self._process.stdin.write(data.encode())
        self._process.stdin.flush()

    def _recv(self, timeout: float = 30.0) -> dict:
        """Receive a JSON-RPC message from the subprocess stdout."""
        try:
            return self._recv_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(
                f"No response from MCP server within {timeout}s"
            )

    def _initialize(self):
        """Perform MCP handshake: initialize + notifications/initialized."""
        self._msg_id += 1
        self._send({
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "vk-mcp-client", "version": "0.1.0"},
            },
        })
        self._recv()  # wait for initialize response
        # Send initialized notification (no id, no response expected)
        self._send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool and return the parsed result.

        Returns parsed JSON if the result text is valid JSON,
        otherwise returns the raw text string.

        Raises VkMcpError if the server returns an error response.
        """
        self._msg_id += 1
        msg_id = self._msg_id
        self._send({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        response = self._recv()

        if "error" in response:
            err = response["error"]
            raise VkMcpError(
                f"MCP error {err['code']}: {err['message']}"
            )

        # Extract text from content array
        content = response.get("result", {}).get("content", [])
        text = ""
        for item in content:
            if item.get("type") == "text":
                text = item["text"]
                break

        # Try to parse as JSON
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    # --- Convenience methods ---

    def create_issue(self, project_id: str, title: str, **kwargs) -> Any:
        return self.call_tool("create_issue", {
            "project_id": project_id, "title": title, **kwargs
        })

    def update_issue(self, issue_id: str, **kwargs) -> Any:
        return self.call_tool("update_issue", {"issue_id": issue_id, **kwargs})

    def get_issue(self, issue_id: str) -> Any:
        return self.call_tool("get_issue", {"issue_id": issue_id})

    def delete_issue(self, issue_id: str) -> Any:
        return self.call_tool("delete_issue", {"issue_id": issue_id})

    def list_issues(self, project_id: str, **kwargs) -> Any:
        return self.call_tool("list_issues", {
            "project_id": project_id, **kwargs
        })

    def start_workspace(
        self, name: str, executor: str, repositories: list[str], **kwargs
    ) -> Any:
        return self.call_tool("start_workspace", {
            "name": name, "executor": executor,
            "repositories": repositories, **kwargs
        })

    def list_workspaces(self, **kwargs) -> Any:
        return self.call_tool("list_workspaces", {**kwargs})

    def update_workspace(self, workspace_id: str, **kwargs) -> Any:
        return self.call_tool("update_workspace", {
            "workspace_id": workspace_id, **kwargs
        })

    def list_repos(self) -> Any:
        return self.call_tool("list_repos", {})

    def link_workspace_issue(
        self, workspace_id: str, issue_id: str
    ) -> Any:
        return self.call_tool("link_workspace_issue", {
            "workspace_id": workspace_id, "issue_id": issue_id
        })

    def close(self):
        """Terminate the subprocess."""
        if hasattr(self, "_process") and self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)
