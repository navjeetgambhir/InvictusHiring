import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, Response
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.core.dependencies import get_current_user, CurrentUser
from app.db.models import JDRequest, JDDraft, JobPosting, PastJD
from app.services.supervisor import agent2_publish
from app.services.rag import embed
from app.services.platforms.indeed import FEED_DIR
from app.services.platforms.google_jobs import JOBS_DIR

router = APIRouter(prefix="/jobs", tags=["Job Poster"])


class PublishOptions(BaseModel):
    expires_at: datetime | None = None       # ISO8601 — null means no expiry
    max_applications: int | None = None      # null means unlimited


async def _save_to_past_jds(title: str, department: str, content: str) -> None:
    """Embed the published JD and upsert it into past_jds for future RAG retrieval."""
    try:
        embedding = await embed(content)
        async with AsyncSessionLocal() as db:
            db.add(PastJD(title=title, department=department, content=content, embedding=embedding))
            await db.commit()
        logger.info(f"Saved published JD to past_jds | title='{title}'")
    except Exception as exc:
        logger.warning(f"Failed to save JD to past_jds | title='{title}' error={exc}")


async def _get_approved_request(session_id: uuid.UUID, db: AsyncSession) -> tuple[JDRequest, JDDraft]:
    result = await db.execute(select(JDRequest).where(JDRequest.session_id == session_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Session not found")
    if req.status not in ("approved", "published"):
        raise HTTPException(status_code=400, detail="JD must be approved before posting")

    draft_result = await db.execute(
        select(JDDraft)
        .where(JDDraft.request_id == req.id)
        .order_by(JDDraft.version.desc())
        .limit(1)
    )
    draft = draft_result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=400, detail="No draft found for this session")
    return req, draft


@router.post("/post/{session_id}")
async def post_to_job_boards(
    session_id: uuid.UUID,
    options: PublishOptions = PublishOptions(),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Agent 2 — Job Poster.
    Takes an approved JD, reformats it for LinkedIn / Indeed UK / Google Jobs via OpenAI,
    and streams NDJSON progress back to the client.
    On completion the JD status moves to 'published'.
    Accepts optional expires_at (ISO8601) and max_applications to cap the posting.
    """
    req, draft = await _get_approved_request(session_id, db)
    logger.info(
        f"Job poster triggered | session_id={session_id} title='{req.title}' "
        f"expires_at={options.expires_at} max_applications={options.max_applications}"
    )

    import json

    postings: dict[str, dict[str, Any]] = {}

    async def generate():
        async for line in agent2_publish(draft.content, req.title, str(session_id)):
            yield line

            try:
                event = json.loads(line)
            except Exception:
                continue

            if event.get("type") == "posted":
                postings[event["platform_id"]] = {
                    "content": event["content"],
                    "url": event["url"],
                    "platform": event["platform"],
                }

            if event.get("type") == "done":
                # Use a fresh session so the commit is not affected by the
                # request-scoped session lifecycle ending before the generator finishes.
                async with AsyncSessionLocal() as write_db:
                    write_req = await write_db.get(JDRequest, req.id)
                    if write_req:
                        write_req.status = "published"
                        write_req.published_at = datetime.now(timezone.utc)
                        write_req.expires_at = options.expires_at
                        write_req.max_applications = options.max_applications
                    for pid, data in postings.items():
                        write_db.add(JobPosting(
                            request_id=req.id,
                            platform=pid,
                            formatted_content=data["content"],
                            post_url=data["url"],
                            status="posted",
                        ))
                    await write_db.commit()
                logger.info(
                    f"JD published | session_id={session_id} platforms={list(postings.keys())} "
                    f"expires_at={options.expires_at} max_applications={options.max_applications}"
                )
                asyncio.create_task(_save_to_past_jds(req.title, req.department, draft.content))

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.get("/postings/{session_id}")
async def get_postings(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return all platform postings for a session."""
    result = await db.execute(select(JDRequest).where(JDRequest.session_id == session_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Session not found")

    postings_result = await db.execute(
        select(JobPosting).where(JobPosting.request_id == req.id)
    )
    postings = postings_result.scalars().all()
    return [
        {
            "platform": p.platform,
            "post_url": p.post_url,
            "status": p.status,
            "posted_at": p.posted_at.isoformat(),
        }
        for p in postings
    ]


# ── Static file routes for job board crawlers ─────────────────────────────────

@router.get("/indeed-feed/{session_id}.xml", include_in_schema=False)
async def serve_indeed_feed(session_id: str):
    """Serve the Indeed XML job feed for a session. Indeed crawls this URL."""
    path = FEED_DIR / f"{session_id}.xml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Feed not found")
    return Response(content=path.read_text(encoding="utf-8"), media_type="application/xml")


@router.get("/jobs/{session_id}", include_in_schema=False)
async def serve_google_job_page(session_id: str):
    """
    Serve the Google Jobs HTML page with schema.org/JobPosting JSON-LD.
    Google's crawler indexes this URL after the Indexing API notification.
    """
    path = JOBS_DIR / f"{session_id}.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job page not found")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))