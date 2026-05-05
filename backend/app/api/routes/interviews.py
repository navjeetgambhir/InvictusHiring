"""Interview scheduling routes — HR/HM only (requires JWT auth)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.db.models import CandidateApplication, InterviewInvitation, JDRequest
from app.db.queries import get_request_or_404
from app.services.interview_agent import generate_interview_invitation, generate_ics
from app.services.email_sender import send_interview_email

router = APIRouter(prefix="/interviews", tags=["Interviews"])


class ApproveEmailPayload(BaseModel):
    recipient: str     # candidate email (HR can override)
    subject: str
    body: str


class SchedulePayload(BaseModel):
    scheduled_at: datetime
    format: str                # phone | video | in_person
    location: str = ""
    notes: str = ""
    duration_minutes: int = 60


def _invitation_to_dict(inv: InterviewInvitation) -> dict:
    return {
        "id": str(inv.id),
        "application_id": str(inv.application_id),
        "email_subject": inv.email_subject,
        "email_body": inv.email_body,
        "interview_questions": inv.interview_questions,
        "final_recipient": inv.final_recipient,
        "final_subject": inv.final_subject,
        "final_body": inv.final_body,
        "email_approved_at": inv.email_approved_at.isoformat() if inv.email_approved_at else None,
        "email_sent_at": inv.email_sent_at.isoformat() if inv.email_sent_at else None,
        "email_send_error": inv.email_send_error,
        "created_at": inv.created_at.isoformat(),
    }


def _app_interview_dict(app: CandidateApplication, invitation: InterviewInvitation | None) -> dict:
    return {
        "id": str(app.id),
        "name": app.name,
        "email": app.email,
        "phone": app.phone,
        "screening_score": app.screening_score,
        "screening_recommendation": app.screening_recommendation,
        "screening_summary": app.screening_summary,
        "shortlisted": app.shortlisted,
        "interview_status": app.interview_status,
        "interview_scheduled_at": app.interview_scheduled_at.isoformat() if app.interview_scheduled_at else None,
        "interview_format": app.interview_format,
        "interview_location": app.interview_location,
        "interview_notes": app.interview_notes,
        "invitation": _invitation_to_dict(invitation) if invitation else None,
    }


@router.post("/shortlist/{application_id}")
async def toggle_shortlist(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """Toggle shortlist status for a candidate application."""
    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.shortlisted = not app.shortlisted
    await db.commit()
    logger.info(f"Application {application_id} shortlisted={app.shortlisted}")
    return {"application_id": str(application_id), "shortlisted": app.shortlisted}


@router.post("/generate/{application_id}")
async def generate_invitation(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """Generate AI interview invitation email + tailored questions for a candidate."""
    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    try:
        return await generate_interview_invitation(app, db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate invitation: {exc}")


@router.post("/approve-email/{invitation_id}")
async def approve_and_send_email(
    invitation_id: uuid.UUID,
    payload: ApproveEmailPayload,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    HR approves the (optionally edited) invitation email and sends it to the candidate.
    Stores the final recipient/subject/body regardless of whether SMTP is configured.
    If SMTP is not configured the invitation is marked approved but no email is dispatched.
    """
    result = await db.execute(
        select(InterviewInvitation).where(InterviewInvitation.id == invitation_id)
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.email_approved_at:
        raise HTTPException(status_code=409, detail="This invitation has already been approved and sent")

    now = datetime.now(timezone.utc)
    invitation.final_recipient = payload.recipient.strip()
    invitation.final_subject = payload.subject.strip()
    invitation.final_body = payload.body.strip()
    invitation.email_approved_at = now

    email_sent = False
    send_error: str | None = None
    try:
        email_sent = await send_interview_email(
            to=invitation.final_recipient,
            subject=invitation.final_subject,
            body=invitation.final_body,
        )
        if email_sent:
            invitation.email_sent_at = datetime.now(timezone.utc)
    except Exception as exc:
        send_error = str(exc)
        invitation.email_send_error = send_error
        logger.error(f"Failed to send interview email for invitation {invitation_id}: {exc}")

    await db.commit()
    await db.refresh(invitation)

    logger.info(
        f"Interview invitation approved | invitation={invitation_id} "
        f"to={invitation.final_recipient} sent={email_sent}"
    )
    return _invitation_to_dict(invitation)


@router.post("/schedule/{application_id}")
async def schedule_interview(
    application_id: uuid.UUID,
    payload: SchedulePayload,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """Set interview date/time, format, and location for a shortlisted candidate."""
    if payload.format not in ("phone", "video", "in_person"):
        raise HTTPException(status_code=400, detail="format must be phone, video, or in_person")

    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.interview_status = "scheduled"
    app.interview_scheduled_at = payload.scheduled_at
    app.interview_format = payload.format
    app.interview_location = payload.location or None
    app.interview_notes = payload.notes or None
    await db.commit()
    await db.refresh(app)

    logger.info(
        f"Interview scheduled | application={application_id} "
        f"at={payload.scheduled_at.isoformat()} format={payload.format}"
    )
    return {
        "application_id": str(application_id),
        "interview_status": app.interview_status,
        "interview_scheduled_at": app.interview_scheduled_at.isoformat() if app.interview_scheduled_at else None,
        "interview_format": app.interview_format,
        "interview_location": app.interview_location,
        "interview_notes": app.interview_notes,
    }


@router.get("/session/{session_id}")
async def get_session_interviews(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """All shortlisted candidates + interview details for a job session."""
    req = await get_request_or_404(session_id, db)

    apps = (await db.execute(
        select(CandidateApplication)
        .where(
            CandidateApplication.request_id == req.id,
            CandidateApplication.shortlisted == True,  # noqa: E712
        )
        .order_by(CandidateApplication.applied_at.desc())
    )).scalars().all()

    if not apps:
        return []

    # Single query for the latest invitation per application (avoids N+1)
    app_ids = [app.id for app in apps]
    latest_sq = (
        select(InterviewInvitation.application_id, func.max(InterviewInvitation.created_at).label("max_at"))
        .where(InterviewInvitation.application_id.in_(app_ids))
        .group_by(InterviewInvitation.application_id)
        .subquery()
    )
    inv_rows = (await db.execute(
        select(InterviewInvitation).join(
            latest_sq,
            (InterviewInvitation.application_id == latest_sq.c.application_id)
            & (InterviewInvitation.created_at == latest_sq.c.max_at),
        )
    )).scalars().all()
    invitations_by_app = {inv.application_id: inv for inv in inv_rows}

    return [_app_interview_dict(app, invitations_by_app.get(app.id)) for app in apps]


@router.get("/ics/{application_id}")
async def download_ics(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """Download .ics calendar file for a scheduled interview."""
    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app or not app.interview_scheduled_at:
        raise HTTPException(status_code=404, detail="No scheduled interview found for this application")

    job_result = await db.execute(
        select(JDRequest).where(JDRequest.id == app.request_id)
    )
    job = job_result.scalar_one_or_none()

    ics_content = generate_ics(
        candidate_name=app.name,
        job_title=job.title if job else "Role",
        scheduled_at=app.interview_scheduled_at,
        location=app.interview_location or "",
    )

    filename = f"interview_{app.name.replace(' ', '_').lower()}.ics"
    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )