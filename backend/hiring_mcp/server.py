"""
InvictusHiring MCP Server — stdio transport

Tools
─────
  PostgreSQL / pgvector
    db_list_sessions       — list recent JD sessions
    db_get_session         — full session detail (request, draft, chat, postings)
    db_search_similar_jds  — cosine-similarity search via pgvector
    db_get_postings        — job postings for a session

  LinkedIn
    linkedin_post_job      — publish job to LinkedIn UGC Posts API

  Indeed
    indeed_post_job        — generate XML feed + optional re-index notify

  Google Jobs
    google_jobs_post_job   — generate JSON-LD page + optional Indexing API notify

Run standalone:
    PYTHONPATH=backend python backend/mcp/server.py
"""

import sys
from pathlib import Path

# Ensure `app.*` imports resolve when this script is run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.db.models import ChatMessage, JDDraft, JDRequest, JobPosting
from app.services.platforms.google_jobs import post_to_google_jobs
from app.services.platforms.indeed import post_to_indeed
from app.services.platforms.linkedin import post_to_linkedin
from app.services.rag import embed

mcp = FastMCP("invictus-hiring")

# ── PostgreSQL / pgvector ─────────────────────────────────────────────────────


@mcp.tool()
async def db_list_sessions(limit: int = 20) -> list[dict]:
    """List recent JD drafting sessions ordered by creation date (newest first)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(JDRequest).order_by(JDRequest.created_at.desc()).limit(limit)
        )
        return [
            {
                "session_id": str(r.session_id),
                "title": r.title,
                "department": r.department,
                "location": r.location,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in result.scalars().all()
        ]


@mcp.tool()
async def db_get_session(session_id: str) -> dict:
    """Return full session detail: request fields, latest draft, chat history, and job postings."""
    async with AsyncSessionLocal() as db:
        req_result = await db.execute(
            select(JDRequest).where(JDRequest.session_id == session_id)
        )
        req = req_result.scalar_one_or_none()
        if not req:
            return {"error": f"Session {session_id} not found"}

        draft_result = await db.execute(
            select(JDDraft)
            .where(JDDraft.request_id == req.id)
            .order_by(JDDraft.version.desc())
            .limit(1)
        )
        draft = draft_result.scalar_one_or_none()

        msg_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.request_id == req.id)
            .order_by(ChatMessage.created_at)
        )

        posting_result = await db.execute(
            select(JobPosting).where(JobPosting.request_id == req.id)
        )

        return {
            "session_id": str(req.session_id),
            "title": req.title,
            "department": req.department,
            "location": req.location,
            "salary_band": req.salary_band,
            "required_skills": req.required_skills,
            "nice_to_have_skills": req.nice_to_have_skills,
            "status": req.status,
            "created_at": req.created_at.isoformat(),
            "latest_draft": (
                {"version": draft.version, "content": draft.content}
                if draft
                else None
            ),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "ts": m.created_at.isoformat(),
                }
                for m in msg_result.scalars().all()
            ],
            "postings": [
                {
                    "platform": p.platform,
                    "post_url": p.post_url,
                    "status": p.status,
                    "posted_at": p.posted_at.isoformat(),
                }
                for p in posting_result.scalars().all()
            ],
        }


@mcp.tool()
async def db_search_similar_jds(
    query: str,
    top_k: int = 5,
    threshold: float = 0.70,
) -> list[dict]:
    """
    Semantic similarity search over past JDs using pgvector cosine distance.
    Returns up to top_k results with similarity >= threshold.
    Content is truncated to 500 chars for readability.
    """
    embedding = await embed(query)
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text("""
                SELECT title, department, content,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM past_jds
                WHERE 1 - (embedding <=> CAST(:embedding AS vector)) >= :threshold
                ORDER BY similarity DESC
                LIMIT :k
            """),
            {"embedding": str(embedding), "threshold": threshold, "k": top_k},
        )
        return [
            {
                "title": r.title,
                "department": r.department,
                "content": r.content[:500],
                "similarity": round(float(r.similarity), 4),
            }
            for r in rows.fetchall()
        ]


@mcp.tool()
async def db_get_postings(session_id: str) -> list[dict]:
    """Return all platform job postings (LinkedIn, Indeed, Google Jobs) for a given session."""
    async with AsyncSessionLocal() as db:
        req_result = await db.execute(
            select(JDRequest).where(JDRequest.session_id == session_id)
        )
        req = req_result.scalar_one_or_none()
        if not req:
            return [{"error": f"Session {session_id} not found"}]

        result = await db.execute(
            select(JobPosting).where(JobPosting.request_id == req.id)
        )
        return [
            {
                "platform": p.platform,
                "post_url": p.post_url,
                "status": p.status,
                "posted_at": p.posted_at.isoformat(),
            }
            for p in result.scalars().all()
        ]


# ── LinkedIn ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def linkedin_post_job(title: str, formatted_content: str) -> dict:
    """
    Publish an approved job description to LinkedIn via the UGC Posts API.
    Requires LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_URN in backend/.env.
    Returns {"success": true, "url": "<post_url>"} on success.
    """
    if not settings.linkedin_access_token:
        return {"success": False, "error": "LINKEDIN_ACCESS_TOKEN not configured in .env"}
    if not settings.linkedin_author_urn:
        return {"success": False, "error": "LINKEDIN_AUTHOR_URN not configured in .env"}
    try:
        url = await post_to_linkedin(
            access_token=settings.linkedin_access_token,
            author_urn=settings.linkedin_author_urn,
            title=title,
            formatted_content=formatted_content,
        )
        return {"success": True, "url": url}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Indeed ────────────────────────────────────────────────────────────────────


@mcp.tool()
async def indeed_post_job(
    session_id: str,
    title: str,
    formatted_content: str,
    location: str = "United Kingdom",
    salary: str = "",
    job_type: str = "Full-time",
) -> dict:
    """
    Generate an Indeed XML feed for the job and optionally notify Indeed to re-index it.
    INDEED_PUBLISHER_ID in .env enables the re-index ping; works without it.
    Returns {"success": true, "feed_url": "<url>"} on success.
    """
    try:
        url = await post_to_indeed(
            session_id=session_id,
            title=title,
            formatted_content=formatted_content,
            base_url=settings.app_base_url,
            publisher_id=settings.indeed_publisher_id or None,
            location=location,
            salary=salary,
            job_type=job_type,
        )
        return {"success": True, "feed_url": url}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Google Jobs ───────────────────────────────────────────────────────────────


@mcp.tool()
async def google_jobs_post_job(
    session_id: str,
    title: str,
    formatted_content: str,
    location: str = "United Kingdom",
    salary: str = "",
    job_type: str = "FULL_TIME",
) -> dict:
    """
    Generate a schema.org/JobPosting JSON-LD page and optionally notify the
    Google Indexing API so the job appears in search results quickly.
    GOOGLE_SERVICE_ACCOUNT_JSON in .env enables the Indexing API call; works without it.
    Returns {"success": true, "page_url": "<url>"} on success.
    """
    try:
        url = await post_to_google_jobs(
            session_id=session_id,
            title=title,
            formatted_content=formatted_content,
            base_url=settings.app_base_url,
            service_account_json=settings.google_service_account_json or None,
            location=location,
            salary=salary,
            job_type=job_type,
        )
        return {"success": True, "page_url": url}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()