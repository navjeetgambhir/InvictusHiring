"""
Singleton MCP client that connects to the hiring_mcp stdio server.

Lifecycle is managed by FastAPI's lifespan — call start() on startup and the
async context managers stay open for the process lifetime. All agents call
query() / get_session() / search_similar_jds() rather than hitting SQLAlchemy.
"""

import json
import sys
from pathlib import Path
from typing import Any

from loguru import logger
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

_session: ClientSession | None = None

# Context-manager objects we must keep alive for the process lifetime
_stdio_ctx = None
_session_ctx = None


def _server_params() -> StdioServerParameters:
    repo_root = Path(__file__).parent.parent.parent.parent  # backend/../..
    backend_dir = repo_root / "backend"
    server_script = backend_dir / "hiring_mcp" / "server.py"
    return StdioServerParameters(
        command=sys.executable,
        args=[str(server_script)],
        env={"PYTHONPATH": str(backend_dir)},
    )


async def start() -> None:
    """Enter stdio and session context managers, storing the live session."""
    global _session, _stdio_ctx, _session_ctx
    try:
        params = _server_params()
        _stdio_ctx = stdio_client(params)
        read, write = await _stdio_ctx.__aenter__()
        _session_ctx = ClientSession(read, write)
        _session = await _session_ctx.__aenter__()
        await _session.initialize()
        tools = await _session.list_tools()
        logger.info(f"MCP client connected | tools={[t.name for t in tools.tools]}")
    except Exception as exc:
        logger.warning(f"MCP client failed to start — agents will fall back to SQLAlchemy | {exc}")
        _session = None


async def stop() -> None:
    """Exit context managers on app shutdown."""
    global _session, _stdio_ctx, _session_ctx
    try:
        if _session_ctx:
            await _session_ctx.__aexit__(None, None, None)
        if _stdio_ctx:
            await _stdio_ctx.__aexit__(None, None, None)
    except Exception as exc:
        logger.warning(f"MCP client shutdown error | {exc}")
    finally:
        _session = None
        _stdio_ctx = None
        _session_ctx = None


def get() -> ClientSession | None:
    return _session


async def query(sql: str) -> list[dict[str, Any]]:
    """Execute a read-only SQL query via the MCP server. Returns rows as dicts."""
    if _session is None:
        raise RuntimeError("MCP client is not connected")
    result = await _session.call_tool("db_query", {"sql": sql})
    for item in result.content:
        if hasattr(item, "text"):
            return json.loads(item.text)
    return []


async def get_session_context(session_id: str) -> dict[str, Any]:
    """Fetch session detail via the MCP db_get_session tool."""
    if _session is None:
        raise RuntimeError("MCP client is not connected")
    result = await _session.call_tool("db_get_session", {"session_id": session_id})
    for item in result.content:
        if hasattr(item, "text"):
            return json.loads(item.text)
    return {}