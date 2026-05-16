"""
Integration tests — ORM model CRUD against a real Postgres database.

Verifies that SQLAlchemy models align with the actual schema, FK constraints
fire correctly, and queries return expected results.
"""
import uuid

import pytest
from sqlalchemy import select

from app.db.models import (
    JDRequest,
    JDDraft,
    ChatMessage,
    CandidateApplication,
    JobPosting,
    InterviewInvitation,
)

pytestmark = pytest.mark.asyncio


# ── JDRequest ─────────────────────────────────────────────────────────────────

async def test_create_and_query_jd_request(db):
    req = JDRequest(
        submitted_by="hr@test.com",
        role="hr",
        title="Backend Engineer",
        department="Engineering",
        location="London",
        salary_band="£70k–£90k",
        required_skills=["Python", "FastAPI"],
        nice_to_have_skills=["Docker"],
        company_description="A fintech company.",
    )
    db.add(req)
    await db.flush()

    result = await db.execute(select(JDRequest).where(JDRequest.session_id == req.session_id))
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.title == "Backend Engineer"
    assert fetched.status == "drafting"
    assert fetched.required_skills == ["Python", "FastAPI"]


async def test_jd_request_defaults(db):
    req = JDRequest(
        submitted_by="hm@test.com",
        role="hm",
        title="Data Scientist",
        department="Analytics",
        location="Remote",
        salary_band="£80k",
        required_skills=["Python"],
        nice_to_have_skills=[],
        company_description="Corp.",
    )
    db.add(req)
    await db.flush()

    assert req.status == "drafting"
    assert req.session_id is not None
    assert req.created_at is not None
    assert req.expires_at is None
    assert req.max_applications is None


# ── JDDraft ───────────────────────────────────────────────────────────────────

async def test_create_draft_linked_to_request(db):
    req = JDRequest(
        submitted_by="hr@test.com", role="hr", title="SWE", department="Eng",
        location="London", salary_band="£60k", required_skills=["Go"],
        nice_to_have_skills=[], company_description="Corp.",
    )
    db.add(req)
    await db.flush()

    draft = JDDraft(request_id=req.id, version=1, content="## Job Title\nSWE\n")
    db.add(draft)
    await db.flush()

    result = await db.execute(
        select(JDDraft).where(JDDraft.request_id == req.id).order_by(JDDraft.version.desc())
    )
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.version == 1
    assert "SWE" in fetched.content
    assert fetched.rejection_feedback is None


async def test_multiple_draft_versions(db):
    req = JDRequest(
        submitted_by="hr@test.com", role="hr", title="PM", department="Product",
        location="London", salary_band="£90k", required_skills=["Jira"],
        nice_to_have_skills=[], company_description="Corp.",
    )
    db.add(req)
    await db.flush()

    for version in range(1, 4):
        db.add(JDDraft(request_id=req.id, version=version, content=f"Draft v{version}"))
    await db.flush()

    result = await db.execute(
        select(JDDraft).where(JDDraft.request_id == req.id).order_by(JDDraft.version.desc())
    )
    drafts = result.scalars().all()

    assert len(drafts) == 3
    assert drafts[0].version == 3  # most recent first


# ── CandidateApplication ──────────────────────────────────────────────────────

async def test_create_candidate_application(db):
    req = JDRequest(
        submitted_by="hr@test.com", role="hr", title="Designer", department="Product",
        location="London", salary_band="£50k", required_skills=["Figma"],
        nice_to_have_skills=[], company_description="Corp.",
    )
    db.add(req)
    await db.flush()

    app = CandidateApplication(
        request_id=req.id,
        name="Jane Smith",
        email="jane@example.com",
        phone="07700900000",
        cover_letter="I am very interested in this role.",
    )
    db.add(app)
    await db.flush()

    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.request_id == req.id)
    )
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.name == "Jane Smith"
    assert fetched.screening_status == "pending"
    assert fetched.shortlisted is False
    assert fetched.outcome is None


async def test_candidate_screening_fields_update(db):
    req = JDRequest(
        submitted_by="hr@test.com", role="hr", title="Analyst", department="Finance",
        location="London", salary_band="£45k", required_skills=["Excel"],
        nice_to_have_skills=[], company_description="Corp.",
    )
    db.add(req)
    await db.flush()

    app = CandidateApplication(
        request_id=req.id, name="Bob Jones", email="bob@example.com",
    )
    db.add(app)
    await db.flush()

    app.screening_status = "screened"
    app.screening_score = 78
    app.screening_recommendation = "shortlist"
    app.screening_strengths = ["Strong Excel skills", "Relevant experience"]
    app.screening_gaps = ["No Python"]
    await db.flush()

    result = await db.execute(
        select(CandidateApplication).where(CandidateApplication.id == app.id)
    )
    fetched = result.scalar_one()

    assert fetched.screening_score == 78
    assert fetched.screening_recommendation == "shortlist"
    assert "Strong Excel skills" in fetched.screening_strengths


# ── JobPosting ────────────────────────────────────────────────────────────────

async def test_create_job_posting(db):
    req = JDRequest(
        submitted_by="hr@test.com", role="hr", title="ML Engineer", department="AI",
        location="London", salary_band="£100k", required_skills=["Python"],
        nice_to_have_skills=[], company_description="AI Corp.",
    )
    db.add(req)
    await db.flush()

    posting = JobPosting(
        request_id=req.id,
        platform="linkedin",
        formatted_content="Formatted JD for LinkedIn...",
        post_url="https://linkedin.com/jobs/123",
        status="posted",
    )
    db.add(posting)
    await db.flush()

    result = await db.execute(
        select(JobPosting).where(JobPosting.request_id == req.id)
    )
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.platform == "linkedin"
    assert fetched.status == "posted"


# ── InterviewInvitation ───────────────────────────────────────────────────────

async def test_create_interview_invitation(db):
    req = JDRequest(
        submitted_by="hr@test.com", role="hr", title="QA Engineer", department="Eng",
        location="London", salary_band="£60k", required_skills=["Selenium"],
        nice_to_have_skills=[], company_description="Corp.",
    )
    db.add(req)
    await db.flush()

    candidate = CandidateApplication(
        request_id=req.id, name="Alice Green", email="alice@example.com",
    )
    db.add(candidate)
    await db.flush()

    invitation = InterviewInvitation(
        application_id=candidate.id,
        email_subject="Interview Invitation — QA Engineer",
        email_body="Dear Alice, we'd like to invite you...",
        interview_questions=["Describe your testing approach.", "What tools have you used?"],
    )
    db.add(invitation)
    await db.flush()

    result = await db.execute(
        select(InterviewInvitation).where(InterviewInvitation.application_id == candidate.id)
    )
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert "Alice" in fetched.email_body
    assert len(fetched.interview_questions) == 2
    assert fetched.email_sent_at is None


# ── FK constraint ─────────────────────────────────────────────────────────────

async def test_draft_fk_rejects_unknown_request_id(db):
    from sqlalchemy.exc import IntegrityError

    draft = JDDraft(
        request_id=uuid.uuid4(),  # does not exist
        version=1,
        content="Orphan draft",
    )
    db.add(draft)
    with pytest.raises(IntegrityError):
        await db.flush()