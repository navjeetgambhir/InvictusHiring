import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.core.limiter import limiter
from app.db.models import CandidateApplication, JDDraft, JDRequest
from app.db.queries import get_request_or_404
from app.services.cv_screener import CV_DIR, _extract_sync
from app.services.supervisor import agent3_screen
from app.services.email_sender import send_application_confirmation_email
from app.services.ml_predictor import predict_fit, predict_join

router = APIRouter(prefix="/candidates", tags=["Candidates"])

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


def _is_accepting(req: JDRequest, application_count: int) -> bool:
    """Return True if the job is still open (not expired, not at capacity)."""
    now = datetime.now(timezone.utc)
    if req.expires_at and req.expires_at <= now:
        return False
    if req.max_applications is not None and application_count >= req.max_applications:
        return False
    return True


async def _count_applications(req_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(CandidateApplication.request_id == req_id)
    )
    return result.scalar_one()


def _job_row_to_dict(req: JDRequest, draft: JDDraft | None, application_count: int = 0) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    accepting = _is_accepting(req, application_count)
    return {
        "session_id": str(req.session_id),
        "title": req.title,
        "department": req.department,
        "location": req.location,
        "salary_band": req.salary_band,
        "required_skills": req.required_skills,
        "nice_to_have_skills": req.nice_to_have_skills,
        "company_description": req.company_description,
        "posted_at": (req.published_at or req.created_at).isoformat(),
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "max_applications": req.max_applications,
        "application_count": application_count,
        "is_accepting": accepting,
        "content": draft.content if draft else None,
    }


@router.get("/jobs")
async def list_published_jobs(
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 10,
):
    """Public — paginated published JDs for the candidate job board (excludes expired / full)."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    now = datetime.now(timezone.utc)

    latest_version_sq = (
        select(JDDraft.request_id, func.max(JDDraft.version).label("max_version"))
        .group_by(JDDraft.request_id)
        .subquery()
    )

    app_count_sq = (
        select(CandidateApplication.request_id, func.count().label("app_count"))
        .group_by(CandidateApplication.request_id)
        .subquery()
    )

    app_count_col = func.coalesce(app_count_sq.c.app_count, 0)

    base_q = (
        select(JDRequest, JDDraft, app_count_col.label("app_count"))
        .outerjoin(latest_version_sq, latest_version_sq.c.request_id == JDRequest.id)
        .outerjoin(
            JDDraft,
            (JDDraft.request_id == JDRequest.id) & (JDDraft.version == latest_version_sq.c.max_version),
        )
        .outerjoin(app_count_sq, app_count_sq.c.request_id == JDRequest.id)
        .where(JDRequest.status == "published")
        .where((JDRequest.expires_at == None) | (JDRequest.expires_at > now))  # noqa: E711
        .where(
            (JDRequest.max_applications == None) |  # noqa: E711
            (app_count_col < JDRequest.max_applications)
        )
        .order_by(JDRequest.created_at.desc())
    )

    total: int = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar_one()

    rows = (await db.execute(
        base_q.offset((page - 1) * page_size).limit(page_size)
    )).all()

    return {
        "jobs": [_job_row_to_dict(req, draft, app_count) for req, draft, app_count in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),  # ceiling division
    }


@router.get("/jobs/{session_id}")
async def get_job(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Public — single published job by session ID."""
    req = await get_request_or_404(session_id, db)
    if req.status != "published":
        raise HTTPException(status_code=404, detail="Job not found")

    result = await db.execute(
        select(JDDraft)
        .where(JDDraft.request_id == req.id)
        .order_by(JDDraft.version.desc())
        .limit(1)
    )
    draft = result.scalar_one_or_none()
    app_count = await _count_applications(req.id, db)

    return {
        **_job_row_to_dict(req, draft, app_count),
        "additional_context": req.additional_context,
    }


@router.post("/apply/{session_id}", status_code=201)
@limiter.limit("5/hour")
async def apply_for_job(
    request: Request,
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    cover_letter: str = Form(""),
    cv: UploadFile | None = File(None),
    cover_letter_file: UploadFile | None = File(None),
):
    """Public — submit a candidate application with optional CV and cover letter uploads."""
    req = await get_request_or_404(session_id, db)
    if req.status != "published":
        raise HTTPException(status_code=400, detail="This job is not currently accepting applications")

    app_count = await _count_applications(req.id, db)
    if not _is_accepting(req, app_count):
        raise HTTPException(status_code=400, detail="This job posting is no longer accepting applications")

    # ── CV upload ──────────────────────────────────────────────────────────────
    cv_filename: str | None = None
    cv_path: str | None = None

    if cv and cv.filename:
        ext = Path(cv.filename).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"CV must be PDF, DOCX, or TXT (got {ext})")
        data = await cv.read()
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="CV file must be under 5 MB")
        dest = CV_DIR / f"{uuid.uuid4()}{ext}"
        await asyncio.to_thread(dest.write_bytes, data)
        cv_filename = cv.filename
        cv_path = str(dest)

    # ── Cover letter: uploaded file takes priority over typed text ─────────────
    cl_text: str | None = cover_letter.strip() or None
    cl_filename: str | None = None

    if cover_letter_file and cover_letter_file.filename:
        ext = Path(cover_letter_file.filename).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Cover letter must be PDF, DOCX, or TXT (got {ext})",
            )
        cl_data = await cover_letter_file.read()
        if len(cl_data) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="Cover letter file must be under 5 MB")
        try:
            cl_text = await asyncio.to_thread(_extract_sync, cover_letter_file.filename, cl_data)
        except Exception as exc:
            logger.warning(f"Cover letter extraction failed: {exc}")
            raise HTTPException(status_code=422, detail="Could not extract text from cover letter file")
        cl_filename = cover_letter_file.filename

    application = CandidateApplication(
        request_id=req.id,
        name=name.strip(),
        email=email.strip().lower(),
        phone=phone.strip() or None,
        cover_letter=cl_text,
        cover_letter_filename=cl_filename,
        cv_filename=cv_filename,
        cv_path=cv_path,
        screening_status="pending" if cv_path else "failed",
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)

    if cv_path:
        background_tasks.add_task(agent3_screen, application.id, db)
        logger.info(f"Application {application.id} queued for CV screening")

    background_tasks.add_task(
        send_application_confirmation_email,
        application.email,
        application.name,
        req.title,
        req.company_description[:40] if req.company_description else "Invictus Hiring",
    )

    return {"message": "Application submitted successfully", "application_id": str(application.id)}


# ── HR-only endpoints ─────────────────────────────────────────────────────────

def _assert_session_access(req: "JDRequest", user: CurrentUser) -> None:
    """HR sees everything; HM sees only sessions they submitted."""
    if user.role != "hr" and req.submitted_by != user.email:
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/applications/{session_id}")
async def get_applications(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """HR/HM only — list all applications for a session with AI screening results and ML predictions."""
    req = await get_request_or_404(session_id, db)
    _assert_session_access(req, _user)

    apps = (await db.execute(
        select(CandidateApplication)
        .where(CandidateApplication.request_id == req.id)
        .order_by(CandidateApplication.applied_at.desc())
    )).scalars().all()

    return [
        {
            "id": str(a.id),
            "name": a.name,
            "email": a.email,
            "phone": a.phone,
            "cover_letter": a.cover_letter,
            "cover_letter_filename": a.cover_letter_filename,
            "cv_filename": a.cv_filename,
            "has_cv": a.cv_path is not None,
            "screening_status": a.screening_status,
            "screening_score": a.screening_score,
            "screening_summary": a.screening_summary,
            "screening_strengths": a.screening_strengths,
            "screening_gaps": a.screening_gaps,
            "screening_recommendation": a.screening_recommendation,
            "applied_at": a.applied_at.isoformat(),
            "shortlisted": a.shortlisted,
            "interview_status": a.interview_status,
            "interview_scheduled_at": a.interview_scheduled_at.isoformat() if a.interview_scheduled_at else None,
            "interview_format": a.interview_format,
            "interview_location": a.interview_location,
            "interview_notes": a.interview_notes,
            # ML predictions (None when models have not been trained yet)
            "ml_fit_score": predict_fit(a, req),
            "ml_join_score": predict_join(a, req),
            # Outcome labels (set by HR after hiring decision)
            "outcome": a.outcome,
            "offer_extended": a.offer_extended,
            "offer_accepted": a.offer_accepted,
        }
        for a in apps
    ]


@router.get("/applications/{session_id}/cv/{application_id}")
async def download_cv(
    session_id: uuid.UUID,
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """HR/HM only — download the CV for a specific application."""
    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app or not app.cv_path:
        raise HTTPException(status_code=404, detail="CV not found")

    cv_path = Path(app.cv_path)
    if not cv_path.exists():
        raise HTTPException(status_code=404, detail="CV file missing on server")

    return FileResponse(path=cv_path, filename=app.cv_filename or cv_path.name, media_type="application/octet-stream")


# ── ML outcome recording ──────────────────────────────────────────────────────

class OutcomePayload(BaseModel):
    outcome: str                          # hired | rejected | withdrew | no_hire
    offer_extended: bool | None = None
    offer_amount: str | None = None
    offer_date: datetime | None = None
    offer_accepted: bool | None = None
    offer_declined_reason: str | None = None  # competing_offer | salary | role_fit | location | other
    interview_rounds: int | None = None
    days_to_respond: int | None = None


@router.post("/applications/{application_id}/outcome")
async def record_outcome(
    application_id: uuid.UUID,
    payload: OutcomePayload,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    HR records the final hiring outcome and offer details for an application.
    These fields are the target labels for the fit and join-prediction ML models.
    """
    _VALID_OUTCOMES = {"hired", "rejected", "withdrew", "no_hire"}
    if payload.outcome not in _VALID_OUTCOMES:
        raise HTTPException(status_code=400, detail=f"outcome must be one of {sorted(_VALID_OUTCOMES)}")

    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.outcome = payload.outcome
    app.outcome_recorded_at = datetime.now(timezone.utc)

    if payload.offer_extended is not None:
        app.offer_extended = payload.offer_extended
    if payload.offer_amount is not None:
        app.offer_amount = payload.offer_amount
    if payload.offer_date is not None:
        app.offer_date = payload.offer_date
    if payload.offer_accepted is not None:
        app.offer_accepted = payload.offer_accepted
    if payload.offer_declined_reason is not None:
        app.offer_declined_reason = payload.offer_declined_reason
    if payload.interview_rounds is not None:
        app.interview_rounds = payload.interview_rounds
    if payload.days_to_respond is not None:
        app.days_to_respond = payload.days_to_respond

    await db.commit()
    logger.info(
        f"Outcome recorded | application={application_id} outcome={payload.outcome} "
        f"offer_extended={payload.offer_extended} offer_accepted={payload.offer_accepted}"
    )
    return {"application_id": str(application_id), "outcome": app.outcome}