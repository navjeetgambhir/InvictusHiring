import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.core.redis import push_message as redis_push, get_history as redis_history, seed_history
from app.db.models import JDRequest, JDDraft, ChatMessage
from app.services.jd_agent import JD_PROMPT_VERSION
from app.services.supervisor import (
    agent1_extract,
    agent1_draft,
    agent1_chat,
    agent1_revise,
)

router = APIRouter(prefix="/jd", tags=["JD Drafter"])


def _parse_location_salary(content: str) -> tuple[str, str]:
    """Extract location and salary_band from a JD draft using section headers."""
    location = ""
    salary_band = ""

    # Salary: look for currency + number range in "What We Offer" section first, then whole doc
    offer_section = re.search(r"##\s*What We Offer.*?\n(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
    search_text = offer_section.group(1) if offer_section else content
    salary_match = re.search(
        r"[£$€]\s?[\d,]+(?:k|,000)?(?:\s*(?:–|-|to)\s*[£$€]?\s?[\d,]+(?:k|,000)?)?",
        search_text,
        re.IGNORECASE,
    )
    if not salary_match and offer_section:
        salary_match = re.search(
            r"[£$€]\s?[\d,]+(?:k|,000)?(?:\s*(?:–|-|to)\s*[£$€]?\s?[\d,]+(?:k|,000)?)?",
            content,
            re.IGNORECASE,
        )
    if salary_match:
        salary_band = salary_match.group(0).strip()

    # Location: first non-empty line under "Location" section header
    loc_section = re.search(r"##\s*Location.*?\n(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
    if loc_section:
        lines = [l.strip().lstrip("*-•· ") for l in loc_section.group(1).splitlines() if l.strip()]
        if lines:
            location = lines[0]

    return location, salary_band


# ── Request / Response schemas ────────────────────────────────────────────────

class JobRequirementsIn(BaseModel):
    submitted_by: str
    role: Literal["hm", "hr"]
    title: str
    department: str
    location: str
    salary_band: str
    required_skills: list[str] = Field(min_length=1)
    nice_to_have_skills: list[str] = []
    company_description: str
    additional_context: str | None = None


class ChatMessageIn(BaseModel):
    session_id: uuid.UUID
    message: str


class FeedbackIn(BaseModel):
    session_id: uuid.UUID
    feedback: str


class ApprovalIn(BaseModel):
    session_id: uuid.UUID
    approved: bool
    feedback: str | None = None  # required when approved=False


class FreetextDraftIn(BaseModel):
    submitted_by: str
    role: Literal["hm", "hr"]
    text: str  # natural language job requirements


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_request_or_404(session_id: uuid.UUID, db: AsyncSession) -> JDRequest:
    result = await db.execute(select(JDRequest).where(JDRequest.session_id == session_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Session not found")
    return req


async def _latest_draft(request_id: uuid.UUID, db: AsyncSession) -> JDDraft | None:
    result = await db.execute(
        select(JDDraft)
        .where(JDDraft.request_id == request_id)
        .order_by(JDDraft.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _chat_history(request_id: uuid.UUID, session_id: str, db: AsyncSession) -> list[dict]:
    """Read history from Redis; fall back to DB and warm the cache on a miss."""
    cached = await redis_history(session_id)
    if cached is not None:
        logger.debug(f"History cache hit | session={session_id} msgs={len(cached)}")
        return cached

    logger.debug(f"History cache miss | session={session_id} — reading from DB")
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.request_id == request_id)
        .order_by(ChatMessage.created_at)
    )
    db_history = [{"role": m.role, "content": m.content} for m in result.scalars()]
    await seed_history(session_id, db_history)
    return db_history


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/draft-freetext")
async def create_draft_freetext(
    body: FreetextDraftIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Accept free-text job requirements from the chat UI.
    OpenAI extracts structured fields, then streams the JD draft.
    """
    logger.info(f"New freetext draft request | submitted_by={body.submitted_by} role={body.role}")
    requirements = await agent1_extract(body.text)
    requirements["submitted_by"] = body.submitted_by
    requirements["role"] = body.role

    jd_request = JDRequest(
        submitted_by=body.submitted_by,
        role=body.role,
        title=requirements.get("title", "Untitled"),
        department=requirements.get("department", ""),
        location=requirements.get("location", ""),
        salary_band=requirements.get("salary_band", ""),
        required_skills=requirements.get("required_skills", []),
        nice_to_have_skills=requirements.get("nice_to_have_skills", []),
        company_description=requirements.get("company_description", ""),
        additional_context=body.text,
        status="drafting",
    )
    db.add(jd_request)
    await db.flush()
    logger.info(f"JD request created | session_id={jd_request.session_id} title='{jd_request.title}'")

    session_id = str(jd_request.session_id)
    accumulated = []

    async def generate():
        async for chunk in agent1_draft(requirements, db, session_id=session_id):
            accumulated.append(chunk)
            yield chunk

        full_draft = "".join(accumulated)
        db.add(JDDraft(request_id=jd_request.id, version=1, content=full_draft, prompt_version=JD_PROMPT_VERSION))
        db.add(ChatMessage(request_id=jd_request.id, role="user", content=body.text))
        db.add(ChatMessage(request_id=jd_request.id, role="assistant", content=full_draft))
        jd_request.status = "pending_approval"
        await db.commit()
        await redis_push(session_id, "user", body.text)
        await redis_push(session_id, "assistant", full_draft)
        logger.info(f"Draft saved | session_id={jd_request.session_id} chars={len(full_draft)} prompt={JD_PROMPT_VERSION}")
        yield f"\n\n__SESSION_ID__{jd_request.session_id}"

    return StreamingResponse(generate(), media_type="text/plain")


@router.post("/draft")
async def create_draft(
    body: JobRequirementsIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Submit job requirements. Returns a session_id and streams the first JD draft.
    The frontend should open /jd/draft as a streaming endpoint and render chunks live.
    """
    logger.info(f"New structured draft request | submitted_by={body.submitted_by} title='{body.title}'")
    jd_request = JDRequest(
        submitted_by=body.submitted_by,
        role=body.role,
        title=body.title,
        department=body.department,
        location=body.location,
        salary_band=body.salary_band,
        required_skills=body.required_skills,
        nice_to_have_skills=body.nice_to_have_skills,
        company_description=body.company_description,
        additional_context=body.additional_context,
        status="drafting",
    )
    db.add(jd_request)
    await db.flush()  # get the id before streaming

    accumulated = []

    async def generate():
        async for chunk in agent1_draft(body.model_dump(), db, session_id=str(jd_request.session_id)):
            accumulated.append(chunk)
            yield chunk

        full_draft = "".join(accumulated)

        draft = JDDraft(request_id=jd_request.id, version=1, content=full_draft, prompt_version=JD_PROMPT_VERSION)
        db.add(draft)

        db.add(ChatMessage(request_id=jd_request.id, role="assistant", content=full_draft))

        jd_request.status = "pending_approval"
        await db.commit()
        logger.info(f"Draft saved | session_id={jd_request.session_id} chars={len(full_draft)}")
        yield f"\n\n__SESSION_ID__{jd_request.session_id}"

    return StreamingResponse(generate(), media_type="text/plain")


@router.post("/chat")
async def chat(
    body: ChatMessageIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Free-form chat to refine the JD. Streams the assistant reply.
    Use this for conversational edits like "make the tone more formal" or
    "add a remote-first work arrangement clause".
    """
    logger.info(f"Chat message | session_id={body.session_id} msg='{body.message[:60]}…'")
    req = await _get_request_or_404(body.session_id, db)
    latest = await _latest_draft(req.id, db)
    if not latest:
        raise HTTPException(status_code=400, detail="No draft exists for this session yet")

    sid = str(body.session_id)
    history = await _chat_history(req.id, sid, db)

    db.add(ChatMessage(request_id=req.id, role="user", content=body.message))
    await db.flush()

    accumulated = []
    current_version = latest.version

    async def generate():
        async for chunk in agent1_chat(body.message, latest.content, history, session_id=sid):
            accumulated.append(chunk)
            yield chunk

        reply = "".join(accumulated)
        db.add(ChatMessage(request_id=req.id, role="assistant", content=reply))

        # If the reply looks like a full JD draft (markdown headers OR bold-label sections),
        # save it as the new latest draft so approval and the job board see the updated content.
        _looks_like_jd = (
            "##" in reply
            or (reply.startswith("#") and len(reply) > 300)
            or ("**Job Title" in reply and len(reply) > 300)
            or ("**About the Company" in reply and len(reply) > 300)
        )
        if _looks_like_jd:
            next_version = current_version + 1
            db.add(JDDraft(request_id=req.id, version=next_version, content=reply, prompt_version=JD_PROMPT_VERSION))
            new_location, new_salary = _parse_location_salary(reply)
            if new_location:
                req.location = new_location
            if new_salary:
                req.salary_band = new_salary
            logger.info(f"Chat draft updated | session_id={body.session_id} version={next_version}")

        await db.commit()
        await redis_push(sid, "user", body.message)
        await redis_push(sid, "assistant", reply)
        logger.info(f"Chat reply saved | session_id={body.session_id} chars={len(reply)}")

    return StreamingResponse(generate(), media_type="text/plain")


@router.post("/approve")
async def approve_jd(
    body: ApprovalIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    HR/HM approves or rejects the current draft.
    - approved=True  → status moves to 'approved' (ready for job portal posting)
    - approved=False → agent auto-revises with feedback; new draft streamed back
    """
    logger.info(f"Approval action | session_id={body.session_id} approved={body.approved}")
    req = await _get_request_or_404(body.session_id, db)
    latest = await _latest_draft(req.id, db)
    if not latest:
        raise HTTPException(status_code=400, detail="No draft to approve")

    if body.approved:
        req.status = "approved"
        await db.commit()
        logger.info(f"JD approved | session_id={body.session_id} title='{req.title}'")
        return {"status": "approved", "session_id": str(body.session_id)}

    # Rejected — auto-revise
    if not body.feedback:
        raise HTTPException(status_code=422, detail="feedback is required when rejecting")

    sid = str(body.session_id)
    latest.rejection_feedback = body.feedback
    history = await _chat_history(req.id, sid, db)
    feedback_msg = f"[Rejection feedback]: {body.feedback}"
    db.add(ChatMessage(request_id=req.id, role="user", content=feedback_msg))
    await db.flush()

    accumulated = []
    next_version = latest.version + 1

    async def generate():
        async for chunk in agent1_revise(body.feedback or "", latest.content, history, session_id=sid, draft_version=next_version):
            accumulated.append(chunk)
            yield chunk

        revised = "".join(accumulated)
        db.add(JDDraft(request_id=req.id, version=next_version, content=revised, prompt_version=JD_PROMPT_VERSION))
        db.add(ChatMessage(request_id=req.id, role="assistant", content=revised))
        req.status = "pending_approval"
        new_location, new_salary = _parse_location_salary(revised)
        if new_location:
            req.location = new_location
        if new_salary:
            req.salary_band = new_salary
        await db.commit()
        await redis_push(sid, "user", feedback_msg)
        await redis_push(sid, "assistant", revised)
        logger.info(f"Revision saved | session_id={body.session_id} version={next_version} prompt={JD_PROMPT_VERSION}")

    return StreamingResponse(generate(), media_type="text/plain")


class RevertIn(BaseModel):
    session_id: uuid.UUID


@router.post("/revert")
async def revert_to_draft(
    body: RevertIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Revert a published JD back to pending_approval so it can be edited and republished.
    Only allowed when status is 'published' or 'approved'.
    """
    req = await _get_request_or_404(body.session_id, db)
    if req.status not in ("published", "approved"):
        raise HTTPException(status_code=400, detail=f"Cannot revert a JD with status '{req.status}'")
    req.status = "pending_approval"
    await db.commit()
    logger.info(f"JD reverted to pending_approval | session_id={body.session_id} title='{req.title}'")
    return {"status": "pending_approval", "session_id": str(body.session_id)}


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return all JD sessions for the authenticated user, newest first, with last message preview."""
    result = await db.execute(
        select(JDRequest)
        .where(JDRequest.submitted_by == user.email)
        .order_by(JDRequest.created_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()

    rows = []
    for s in sessions:
        # fetch the most recent chat message for preview
        msg_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.request_id == s.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_msg = msg_result.scalar_one_or_none()
        preview = ""
        if last_msg:
            text = last_msg.content.strip().replace("\n", " ")
            preview = text[:80] + ("…" if len(text) > 80 else "")

        rows.append({
            "session_id": str(s.session_id),
            "title": s.title,
            "status": s.status,
            "department": s.department,
            "created_at": s.created_at.isoformat(),
            "last_message_preview": preview,
            "last_message_role": last_msg.role if last_msg else None,
        })
    return rows


@router.get("/session/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return the current state of a JD drafting session including the latest draft."""
    logger.debug(f"Session fetch | session_id={session_id}")
    req = await _get_request_or_404(session_id, db)
    latest = await _latest_draft(req.id, db)
    history = await _chat_history(req.id, str(session_id), db)

    return {
        "session_id": str(session_id),
        "status": req.status,
        "title": req.title,
        "submitted_by": req.submitted_by,
        "latest_draft": latest.content if latest else None,
        "draft_version": latest.version if latest else 0,
        "chat_history": history,
        "published_at": req.published_at.isoformat() if req.published_at else None,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "max_applications": req.max_applications,
    }
