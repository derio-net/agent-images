"""Unit tests for VkMcpClient — JSON-RPC core + convenience methods, no subprocess."""
import importlib.util
import json
import queue
import sys
from pathlib import Path

# Make the script importable as a module
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location(
    "vk_mcp_client", SCRIPT_DIR / "vk_mcp_client.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

VkMcpClient = mod.VkMcpClient
VkMcpError = mod.VkMcpError


# --- Test double ---

class FakeVkMcpClient(VkMcpClient):
    """Subclass that replaces subprocess I/O with queue-based mocks."""

    def __init__(self):
        # Skip __init__ entirely — no subprocess, no threads
        self._msg_id = 0
        self._sent = []        # captures all sent messages
        self._responses = queue.Queue()  # pre-loaded responses

    def _send(self, msg: dict):
        self._sent.append(msg)

    def _recv(self, timeout: float = 5.0) -> dict:
        try:
            return self._responses.get(timeout=0.1)
        except queue.Empty:
            raise TimeoutError("No response queued in FakeVkMcpClient")


# --- Response helpers ---

def _ok_response(result_text: str, msg_id: int = 1) -> dict:
    """Build a successful MCP tools/call response."""
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "content": [{"type": "text", "text": result_text}]
        },
    }


def _error_response(code: int, message: str, msg_id: int = 1) -> dict:
    """Build a JSON-RPC error response."""
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


# --- Core tests ---

class TestCallTool:

    def test_call_tool_sends_correct_jsonrpc(self):
        client = FakeVkMcpClient()
        client._responses.put(_ok_response('{"ok": true}'))
        client.call_tool("test_tool", {"key": "value"})

        assert len(client._sent) == 1
        msg = client._sent[0]
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "tools/call"
        assert msg["params"]["name"] == "test_tool"
        assert msg["params"]["arguments"] == {"key": "value"}
        assert "id" in msg

    def test_call_tool_parses_json_result(self):
        client = FakeVkMcpClient()
        client._responses.put(_ok_response('{"items": [1, 2, 3]}'))
        result = client.call_tool("list_things", {})
        assert result == {"items": [1, 2, 3]}

    def test_call_tool_returns_text_when_not_json(self):
        client = FakeVkMcpClient()
        client._responses.put(_ok_response("plain text result"))
        result = client.call_tool("some_tool", {})
        assert result == "plain text result"

    def test_call_tool_raises_on_error_response(self):
        client = FakeVkMcpClient()
        client._responses.put(_error_response(-32600, "Invalid request"))
        try:
            client.call_tool("bad_tool", {})
            assert False, "Should have raised VkMcpError"
        except VkMcpError as e:
            assert "-32600" in str(e)
            assert "Invalid request" in str(e)

    def test_call_tool_increments_id(self):
        client = FakeVkMcpClient()
        client._responses.put(_ok_response("{}", msg_id=1))
        client._responses.put(_ok_response("{}", msg_id=2))
        client.call_tool("tool_a", {})
        client.call_tool("tool_b", {})

        assert client._sent[0]["id"] == 1
        assert client._sent[1]["id"] == 2


# --- Convenience method tests ---

class TestConvenienceMethods:

    def _make_client(self, response_text: str = "{}") -> FakeVkMcpClient:
        client = FakeVkMcpClient()
        client._responses.put(_ok_response(response_text))
        return client

    def test_create_issue(self):
        client = self._make_client('{"id": "issue-1"}')
        result = client.create_issue("proj-1", "My Issue", description="desc")
        msg = client._sent[0]
        assert msg["params"]["name"] == "create_issue"
        args = msg["params"]["arguments"]
        assert args["project_id"] == "proj-1"
        assert args["title"] == "My Issue"
        assert args["description"] == "desc"
        assert result == {"id": "issue-1"}

    def test_update_issue(self):
        client = self._make_client('{"id": "issue-1"}')
        client.update_issue("issue-1", status="done")
        args = client._sent[0]["params"]["arguments"]
        assert args["issue_id"] == "issue-1"
        assert args["status"] == "done"

    def test_list_issues(self):
        client = self._make_client('[{"id": "i1"}, {"id": "i2"}]')
        result = client.list_issues("proj-1", status="open")
        args = client._sent[0]["params"]["arguments"]
        assert args["project_id"] == "proj-1"
        assert args["status"] == "open"
        assert len(result) == 2

    def test_start_workspace(self):
        client = self._make_client('{"id": "ws-1"}')
        client.start_workspace("my-ws", "claude", ["repo-a"])
        args = client._sent[0]["params"]["arguments"]
        assert args["name"] == "my-ws"
        assert args["executor"] == "claude"
        assert args["repositories"] == ["repo-a"]

    def test_list_workspaces(self):
        client = self._make_client('[{"id": "ws-1"}]')
        result = client.list_workspaces(status="running")
        args = client._sent[0]["params"]["arguments"]
        assert args["status"] == "running"
        assert len(result) == 1

    def test_list_repos(self):
        client = self._make_client('[{"name": "repo-a"}]')
        result = client.list_repos()
        assert client._sent[0]["params"]["name"] == "list_repos"
        assert len(result) == 1

    def test_link_workspace_issue(self):
        client = self._make_client('{"linked": true}')
        client.link_workspace_issue("ws-1", "issue-1")
        args = client._sent[0]["params"]["arguments"]
        assert args["workspace_id"] == "ws-1"
        assert args["issue_id"] == "issue-1"

    def test_get_issue(self):
        client = self._make_client('{"id": "issue-1", "title": "Test"}')
        result = client.get_issue("issue-1")
        args = client._sent[0]["params"]["arguments"]
        assert args["issue_id"] == "issue-1"
        assert result["title"] == "Test"

    def test_delete_issue(self):
        client = self._make_client('{"deleted": true}')
        client.delete_issue("issue-1")
        args = client._sent[0]["params"]["arguments"]
        assert args["issue_id"] == "issue-1"
