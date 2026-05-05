import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.db.models import CandidateApplication, JDDraft, JDRequest
from app.db.queries import get_request_or_404
from app.services.cv_screener import CV_DIR
from app.services.supervisor import agent3_screen

router = APIRouter(prefix="/candidates", tags=["Candidates"])

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


def _job_row_to_dict(req: JDRequest, draft: JDDraft | None) -> dict:
    return {
        "session_id": str(req.session_id),
        "title": req.title,
        "department": req.department,
        "location": req.location,
        "salary_band": req.salary_band,
        "required_skills": req.required_skills,
        "nice_to_have_skills": req.nice_to_have_skills,
        "company_description": req.company_description,
        "posted_at": req.created_at.isoformat(),
        "content": draft.content if draft else None,
    }


@router.get("/jobs")
async def list_published_jobs(db: AsyncSession = Depends(get_db)):
    """Public — all published JDs for the candidate job board."""
    latest_version_sq = (
        select(JDDraft.request_id, func.max(JDDraft.version).label("max_version"))
        .group_by(JDDraft.request_id)
        .subquery()
    )

    rows = (await db.execute(
        select(JDRequest, JDDraft)
        .outerjoin(latest_version_sq, latest_version_sq.c.request_id == JDRequest.id)
        .outerjoin(
            JDDraft,
            (JDDraft.request_id == JDRequest.id) & (JDDraft.version == latest_version_sq.c.max_version),
        )
        .where(JDRequest.status == "published")
        .order_by(JDRequest.created_at.desc())
    )).all()

    return [_job_row_to_dict(req, draft) for req, draft in rows]


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

    return {
        **_job_row_to_dict(req, draft),
        "additional_context": req.additional_context,
    }


@router.post("/apply/{session_id}", status_code=201)
async def apply_for_job(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    cover_letter: str = Form(""),
    cv: UploadFile | None = File(None),
):
    """Public — submit a candidate application with optional CV upload."""
    req = await get_request_or_404(session_id, db)
    if req.status != "published":
        raise HTTPException(status_code=400, detail="This job is not currently accepting applications")

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

    application = CandidateApplication(
        request_id=req.id,
        name=name.strip(),
        email=email.strip().lower(),
        phone=phone.strip() or None,
        cover_letter=cover_letter.strip() or None,
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

    return {"message": "Application submitted successfully", "application_id": str(application.id)}


# ── HR-only endpoints ─────────────────────────────────────────────────────────

@router.get("/applications/{session_id}")
async def get_applications(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """HR/HM only — list all applications for a session with AI screening results."""
    req = await get_request_or_404(session_id, db)

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