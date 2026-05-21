"""Tests for the MCP server (hermes/tools/mcp_server.py)."""
import json
import pytest
from unittest.mock import patch, MagicMock

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hermes.tools.mcp_server import TOOLS, handle_tool_call, get_client


class TestMCPToolDefinitions:
    """Verify tool definitions are well-formed."""

    def test_tools_list_not_empty(self):
        assert len(TOOLS) > 0

    def test_all_tools_have_required_fields(self):
        for tool in TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

    def test_expected_tools_present(self):
        names = [t["name"] for t in TOOLS]
        assert "get_health" in names
        assert "list_documents" in names
        assert "list_escalations" in names
        assert "get_analytics" in names
        assert "ask_kb" in names


class TestGetClient:
    """Test client initialization."""

    def test_get_client_defaults(self):
        with patch.dict(os.environ, {"REPLYIQ_ADMIN_API_URL": "http://test:5000", "REPLYIQ_API_KEY": "key123"}):
            client = get_client()
            assert client.base_url == "http://test:5000"
            assert client.api_key == "key123"

    def test_get_client_uses_env(self):
        with patch.dict(os.environ, {"REPLYIQ_ADMIN_API_URL": "http://custom:8080", "REPLYIQ_API_KEY": "mykey"}, clear=False):
            client = get_client()
            assert client.base_url == "http://custom:8080"
            assert client.api_key == "mykey"


class TestHandleToolCall:
    """Test tool call dispatch."""

    @patch("hermes.tools.mcp_server.get_client")
    def test_get_health(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_json.return_value = {"status": "ok", "db": True}
        mock_get_client.return_value = mock_client

        result = handle_tool_call("get_health", {})
        assert result == {"status": "ok", "db": True}
        mock_client.get_json.assert_called_once_with("/health")

    @patch("hermes.tools.mcp_server.get_client")
    def test_list_documents(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_json.return_value = [{"id": 1, "title": "Doc"}]
        mock_get_client.return_value = mock_client

        result = handle_tool_call("list_documents", {"tenant_slug": "demo"})
        assert result == [{"id": 1, "title": "Doc"}]
        mock_client.get_json.assert_called_once_with("/api/kb/demo/documents")

    @patch("hermes.tools.mcp_server.get_client")
    def test_list_escalations(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_json.return_value = []
        mock_get_client.return_value = mock_client

        result = handle_tool_call("list_escalations", {"tenant_slug": "demo", "status": "open"})
        assert result == []
        mock_client.get_json.assert_called_once_with("/api/escalations/demo?status=open")

    @patch("hermes.tools.mcp_server.get_client")
    def test_list_escalations_default_status(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_json.return_value = []
        mock_get_client.return_value = mock_client

        result = handle_tool_call("list_escalations", {"tenant_slug": "demo"})
        mock_client.get_json.assert_called_once_with("/api/escalations/demo?status=open")

    @patch("hermes.tools.mcp_server.get_client")
    def test_get_analytics(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_json.return_value = {"messages": 100}
        mock_get_client.return_value = mock_client

        result = handle_tool_call("get_analytics", {"tenant_slug": "demo", "days": 14})
        assert result == {"messages": 100}
        mock_client.get_json.assert_called_once_with("/api/admin/demo/analytics?days=14")

    @patch("hermes.tools.mcp_server.get_client")
    def test_get_analytics_default_days(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_json.return_value = {"messages": 50}
        mock_get_client.return_value = mock_client

        result = handle_tool_call("get_analytics", {"tenant_slug": "demo"})
        mock_client.get_json.assert_called_once_with("/api/admin/demo/analytics?days=7")

    @patch("requests.post")
    @patch("hermes.tools.mcp_server.get_client")
    def test_ask_kb(self, mock_get_client, mock_requests_post):
        mock_client = MagicMock()
        mock_client.base_url = "http://localhost:5000"
        mock_client._headers.return_value = {"Authorization": "Bearer key"}
        mock_client.timeout_s = 20
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.json.return_value = {"answer": "42 days", "sources": []}
        mock_response.raise_for_status = MagicMock()
        mock_requests_post.return_value = mock_response

        result = handle_tool_call("ask_kb", {"tenant_slug": "demo", "question": "How many PTO days?"})
        assert result == {"answer": "42 days", "sources": []}

    def test_unknown_tool(self):
        result = handle_tool_call("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]


class TestMCPProtocol:
    """Test the JSON-RPC protocol handling."""

    def test_initialize_response(self):
        """Simulate initialize request."""
        from io import StringIO

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })

        with patch("sys.stdin", StringIO(msg + "\n")):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                from hermes.tools.mcp_server import run_stdio
                # run_stdio reads from stdin until EOF
                run_stdio()

                output = mock_stdout.getvalue().strip()
                response = json.loads(output)
                assert response["jsonrpc"] == "2.0"
                assert response["id"] == 1
                assert "protocolVersion" in response["result"]
                assert response["result"]["serverInfo"]["name"] == "relyiq-admin"

    def test_tools_list_response(self):
        """Simulate tools/list request."""
        from io import StringIO

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })

        with patch("sys.stdin", StringIO(msg + "\n")):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                from hermes.tools.mcp_server import run_stdio
                run_stdio()

                output = mock_stdout.getvalue().strip()
                response = json.loads(output)
                assert response["id"] == 2
                assert "tools" in response["result"]
                assert len(response["result"]["tools"]) == len(TOOLS)

    @patch("hermes.tools.mcp_server.handle_tool_call")
    def test_tools_call_response(self, mock_handle):
        """Simulate tools/call request."""
        from io import StringIO

        mock_handle.return_value = {"status": "ok"}

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_health", "arguments": {}},
        })

        with patch("sys.stdin", StringIO(msg + "\n")):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                from hermes.tools.mcp_server import run_stdio
                run_stdio()

                output = mock_stdout.getvalue().strip()
                response = json.loads(output)
                assert response["id"] == 3
                assert "content" in response["result"]
                content_text = response["result"]["content"][0]["text"]
                assert "ok" in content_text

    def test_unknown_method_error(self):
        """Unknown method returns error."""
        from io import StringIO

        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "unknown/method",
            "params": {},
        })

        with patch("sys.stdin", StringIO(msg + "\n")):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                from hermes.tools.mcp_server import run_stdio
                run_stdio()

                output = mock_stdout.getvalue().strip()
                response = json.loads(output)
                assert response["id"] == 4
                assert "error" in response
                assert response["error"]["code"] == -32601
