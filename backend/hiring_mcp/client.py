"""
InvictusHiring MCP Client

Connects to the MCP server over stdio and provides:
  - mcp_session()   — low-level async context manager → raw ClientSession
  - get_client()    — async context manager → HiringMCPClient (typed wrappers)
  - call_tool()     — one-shot helper for ad-hoc tool calls

Usage
─────
    from backend.mcp.client import get_client

    async with get_client() as client:
        sessions = await client.list_sessions()
        detail   = await client.get_session("<uuid>")
        hits     = await client.search_similar_jds("senior backend engineer Python")
        result   = await client.post_to_linkedin(title, content)
"""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

_SERVER_SCRIPT = Path(__file__).parent / "server.py"  # backend/hiring_mcp/server.py

# The server is launched as a subprocess; PYTHONPATH ensures app.* imports resolve.
_SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=[str(_SERVER_SCRIPT)],
    env={"PYTHONPATH": str(_SERVER_SCRIPT.parent.parent)},
)


def _parse(result) -> Any:
    """Extract and JSON-decode the first text content block from a tool result."""
    if not result.content:
        return None
    text = result.content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


@asynccontextmanager
async def mcp_session():
    """Async context manager that yields an initialised raw MCP ClientSession."""
    async with stdio_client(_SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(tool_name: str, **kwargs: Any) -> Any:
    """Open a session, call one tool by name, return parsed result. Useful for one-offs."""
    async with mcp_session() as session:
        result = await session.call_tool(tool_name, arguments=kwargs)
        return _parse(result)


# ── High-level client ─────────────────────────────────────────────────────────


class HiringMCPClient:
    """
    Typed wrappers around every InvictusHiring MCP tool.
    Obtain via:  async with get_client() as client: ...
    """

    def __init__(self, session: ClientSession) -> None:
        self._s = session

    async def list_tools(self) -> list[str]:
        """Return the names of all tools registered on the server."""
        tools = await self._s.list_tools()
        return [t.name for t in tools.tools]

    # ── PostgreSQL / pgvector ─────────────────────────────────────────────────

    async def list_sessions(self, limit: int = 20) -> list[dict]:
        """List recent JD sessions (newest first)."""
        result = await self._s.call_tool("db_list_sessions", {"limit": limit})
        return _parse(result)

    async def get_session(self, session_id: str) -> dict:
        """Full session detail — request, latest draft, chat history, postings."""
        result = await self._s.call_tool("db_get_session", {"session_id": session_id})
        return _parse(result)

    async def search_similar_jds(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.70,
    ) -> list[dict]:
        """Semantic pgvector search over past JDs."""
        result = await self._s.call_tool(
            "db_search_similar_jds",
            {"query": query, "top_k": top_k, "threshold": threshold},
        )
        return _parse(result)

    async def get_postings(self, session_id: str) -> list[dict]:
        """All platform postings for a session."""
        result = await self._s.call_tool("db_get_postings", {"session_id": session_id})
        return _parse(result)

    # ── LinkedIn ──────────────────────────────────────────────────────────────

    async def post_to_linkedin(self, title: str, formatted_content: str) -> dict:
        """Publish job to LinkedIn. Returns {"success": bool, "url": str}."""
        result = await self._s.call_tool(
            "linkedin_post_job",
            {"title": title, "formatted_content": formatted_content},
        )
        return _parse(result)

    # ── Indeed ────────────────────────────────────────────────────────────────

    async def post_to_indeed(
        self,
        session_id: str,
        title: str,
        formatted_content: str,
        location: str = "United Kingdom",
        salary: str = "",
        job_type: str = "Full-time",
    ) -> dict:
        """Generate Indeed XML feed and optionally notify. Returns {"success": bool, "feed_url": str}."""
        result = await self._s.call_tool(
            "indeed_post_job",
            {
                "session_id": session_id,
                "title": title,
                "formatted_content": formatted_content,
                "location": location,
                "salary": salary,
                "job_type": job_type,
            },
        )
        return _parse(result)

    # ── Google Jobs ───────────────────────────────────────────────────────────

    async def post_to_google_jobs(
        self,
        session_id: str,
        title: str,
        formatted_content: str,
        location: str = "United Kingdom",
        salary: str = "",
        job_type: str = "FULL_TIME",
    ) -> dict:
        """Generate JSON-LD job page and optionally notify Google Indexing API. Returns {"success": bool, "page_url": str}."""
        result = await self._s.call_tool(
            "google_jobs_post_job",
            {
                "session_id": session_id,
                "title": title,
                "formatted_content": formatted_content,
                "location": location,
                "salary": salary,
                "job_type": job_type,
            },
        )
        return _parse(result)


@asynccontextmanager
async def get_client():
    """Async context manager that yields a ready-to-use HiringMCPClient."""
    async with mcp_session() as session:
        yield HiringMCPClient(session)