"""
Interview Scheduling Agent (Agent 5) — AI-powered interview invitation generator.

Given a shortlisted candidate application, this agent:
  1. Loads the candidate profile + job requirements + screening results from DB
  2. Calls OpenAI to draft a personalised interview invitation email and tailored questions
  3. Saves the InterviewInvitation record to DB and returns the generated content

ICS calendar file generation is a pure helper — call generate_ics() once scheduling is confirmed.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


from app.core.config import settings
from app.db.models import CandidateApplication, InterviewInvitation, JDRequest
from app.db.queries import latest_draft
from app.services.agent_telemetry import fire_run

_client = AsyncOpenAI(api_key=settings.openai_api_key)

INTERVIEW_AGENT_PROMPT_VERSION = "interview-v1"

_SYSTEM_PROMPT = """You are an expert HR assistant helping schedule interviews for a UK-based hiring team.
Given a candidate's application details and the job requirements, generate:
1. A professional and warm interview invitation email
2. 5-7 tailored interview questions that assess this specific candidate for this specific role

Guidelines:
- Address the candidate by their first name
- Warm but professional tone (not corporate or cold)
- Reference 1-2 specific strengths from their profile to personalise the email
- Questions should probe role-relevant competencies AND explore any gaps identified in screening
- Questions should be open-ended and behavioural where possible
- UK English spelling and conventions

Return ONLY a JSON object with exactly these fields:
{
  "email_subject": "<concise, specific subject line>",
  "email_body": "<full email body — use plain \\n for line breaks, include placeholder [DATE/TIME] and [FORMAT]>",
  "interview_questions": ["<question 1>", "<question 2>", "..."]
}"""


async def generate_interview_invitation(
    app: CandidateApplication,
    db: AsyncSession,
) -> dict:
    """
    AI generates a personalised interview invitation email + tailored questions.
    Saves InterviewInvitation to DB and returns the record as a dict.
    Caller is responsible for loading and validating `app` before passing it in.
    """
    job_result = await db.execute(
        select(JDRequest).where(JDRequest.id == app.request_id)
    )
    job = job_result.scalar_one_or_none()

    first_name = app.name.split()[0] if app.name else app.name
    strengths_text = "\n".join(f"- {s}" for s in (app.screening_strengths or []))
    gaps_text = "\n".join(f"- {g}" for g in (app.screening_gaps or []))

    user_content = f"""JOB DETAILS
Title: {job.title if job else 'Not specified'}
Department: {job.department if job else 'Not specified'}
Location: {job.location if job else 'Not specified'}
Required Skills: {', '.join(job.required_skills) if job and job.required_skills else 'Not specified'}
Nice-to-Have: {', '.join(job.nice_to_have_skills) if job and job.nice_to_have_skills else 'Not specified'}
Company: Invictus Hiring

CANDIDATE
Name: {app.name} (address as {first_name})
Email: {app.email}
AI Screening Score: {app.screening_score}/100
Recommendation: {app.screening_recommendation or 'N/A'}
Summary: {app.screening_summary or 'No summary available'}
Strengths:
{strengths_text or '- None identified'}
Gaps:
{gaps_text or '- None identified'}
Cover Letter: {(app.cover_letter[:500] + '...') if app.cover_letter and len(app.cover_letter) > 500 else (app.cover_letter or 'Not provided')}

Generate a personalised interview invitation for {first_name}. Leave [DATE/TIME] and [FORMAT] as placeholders in the email body."""

    t0 = time.perf_counter()
    status = "success"
    error_message = None
    input_tokens = output_tokens = None

    try:
        response = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content or "{}")
        email_subject = raw.get("email_subject", f"Interview Invitation — {job.title if job else 'Role'}")
        email_body = raw.get("email_body", "")
        interview_questions = raw.get("interview_questions", [])
        if response.usage:
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
    except Exception as exc:
        logger.error(f"Interview agent failed for application {app.id}: {exc}")
        status = "error"
        error_message = str(exc)
        raise

    latency_ms = int((time.perf_counter() - t0) * 1000)

    invitation = InterviewInvitation(
        application_id=app.id,
        email_subject=email_subject,
        email_body=email_body,
        interview_questions=interview_questions,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    logger.info(
        f"Interview agent | invitation generated | application={app.id} "
        f"candidate='{app.name}' job='{job.title if job else '?'}' | {latency_ms}ms"
    )

    asyncio.create_task(fire_run(
        agent_name="interview_scheduler",
        operation="generate_invitation",
        prompt_version=INTERVIEW_AGENT_PROMPT_VERSION,
        model=settings.openai_model,
        status=status,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        application_id=app.id,
        metrics={
            "score": app.screening_score,
            "recommendation": app.screening_recommendation,
            "questions_count": len(interview_questions),
        },
        error_message=error_message,
    ))

    return {
        "id": str(invitation.id),
        "application_id": str(invitation.application_id),
        "email_subject": invitation.email_subject,
        "email_body": invitation.email_body,
        "interview_questions": invitation.interview_questions,
        "created_at": invitation.created_at.isoformat(),
    }


def generate_ics(
    candidate_name: str,
    job_title: str,
    scheduled_at: datetime,
    duration_minutes: int = 60,
    location: str = "",
) -> str:
    """Generate iCal (.ics) content for a scheduled interview."""
    end_at = scheduled_at + timedelta(minutes=duration_minutes)
    fmt = "%Y%m%dT%H%M%SZ"
    uid = str(uuid.uuid4())
    dtstamp = datetime.now(timezone.utc).strftime(fmt)
    dtstart = scheduled_at.astimezone(timezone.utc).strftime(fmt)
    dtend = end_at.astimezone(timezone.utc).strftime(fmt)

    safe_name = candidate_name.replace(",", "")
    safe_title = job_title.replace(",", "")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Invictus Hiring//Interview Scheduler//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:Interview - {safe_name} for {safe_title}",
    ]
    if location:
        lines.append(f"LOCATION:{location}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines)