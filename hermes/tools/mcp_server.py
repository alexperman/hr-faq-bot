"""
MCP Server for RelyIQ / AlterZahen admin operations.

Exposes the admin API as MCP tools so Kiro (or any MCP client) can:
- Check system health
- List/search knowledge base documents
- View escalations
- Pull analytics summaries
- Manage leads

Run standalone:  python -m hermes.tools.mcp_server
"""

import json
import sys
import os

# Ensure hermes root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hermes.tools.api_client import AdminClient


def get_client() -> AdminClient:
    base_url = os.environ.get("REPLYIQ_ADMIN_API_URL", "http://localhost:5000")
    api_key = os.environ.get("REPLYIQ_API_KEY", os.environ.get("REPLYIQ_ADMIN_API_KEY", ""))
    return AdminClient(base_url=base_url, api_key=api_key)


# ─── Tool Definitions ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_health",
        "description": "Check the RelyIQ application health status including DB connectivity",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_documents",
        "description": "List all knowledge base documents for a tenant",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_slug": {"type": "string", "description": "Tenant slug (e.g. 'demo')"}
            },
            "required": ["tenant_slug"],
        },
    },
    {
        "name": "list_escalations",
        "description": "List unresolved escalations (questions the bot couldn't answer)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_slug": {"type": "string", "description": "Tenant slug"},
                "status": {"type": "string", "enum": ["open", "resolved", "all"], "default": "open"},
            },
            "required": ["tenant_slug"],
        },
    },
    {
        "name": "get_analytics",
        "description": "Get chat analytics summary (message counts, resolution rates)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_slug": {"type": "string", "description": "Tenant slug"},
                "days": {"type": "integer", "default": 7, "description": "Number of days to look back"},
            },
            "required": ["tenant_slug"],
        },
    },
    {
        "name": "ask_kb",
        "description": "Ask a question against the tenant's knowledge base and get an AI answer with citations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_slug": {"type": "string", "description": "Tenant slug"},
                "question": {"type": "string", "description": "The HR question to ask"},
            },
            "required": ["tenant_slug", "question"],
        },
    },
]


def handle_tool_call(name: str, arguments: dict) -> dict:
    """Execute a tool and return the result."""
    client = get_client()

    if name == "get_health":
        return client.get_json("/health")

    elif name == "list_documents":
        slug = arguments["tenant_slug"]
        return client.get_json(f"/api/kb/{slug}/documents")

    elif name == "list_escalations":
        slug = arguments["tenant_slug"]
        status = arguments.get("status", "open")
        return client.get_json(f"/api/escalations/{slug}?status={status}")

    elif name == "get_analytics":
        slug = arguments["tenant_slug"]
        days = arguments.get("days", 7)
        return client.get_json(f"/api/admin/{slug}/analytics?days={days}")

    elif name == "ask_kb":
        slug = arguments["tenant_slug"]
        question = arguments["question"]
        # Use requests directly for POST
        import requests
        url = client.base_url.rstrip("/") + f"/api/chat/{slug}/message"
        r = requests.post(
            url,
            json={"message": question},
            headers=client._headers(),
            timeout=client.timeout_s,
        )
        r.raise_for_status()
        return r.json()

    else:
        return {"error": f"Unknown tool: {name}"}


# ─── MCP stdio Protocol ─────────────────────────────────────────────────────

def run_stdio():
    """Run as an MCP server over stdin/stdout (JSON-RPC 2.0)."""

    def send(msg: dict):
        line = json.dumps(msg)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def respond(id, result):
        send({"jsonrpc": "2.0", "id": id, "result": result})

    def error_response(id, code, message):
        send({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            respond(msg_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "relyiq-admin", "version": "1.0.0"},
            })

        elif method == "notifications/initialized":
            pass  # no response needed

        elif method == "tools/list":
            respond(msg_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = handle_tool_call(tool_name, arguments)
                respond(msg_id, {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                })
            except Exception as e:
                respond(msg_id, {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                })

        elif msg_id is not None:
            error_response(msg_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    run_stdio()
