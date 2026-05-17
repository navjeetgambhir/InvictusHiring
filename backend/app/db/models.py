"""
SQLAlchemy ORM models for the Invictus Hiring platform.

Model hierarchy:
  User                 — HR / HM accounts (PII stored encrypted + blind-indexed)
  JDRequest            — one per JD drafting session (owns drafts, messages, postings, applications)
  JDDraft              — versioned draft text; each rejection produces a new version
  ChatMessage          — full chat history for a session (user + assistant turns)
  JobPosting           — one row per platform per published JD
  PastJD               — published JDs embedded for RAG retrieval
  CandidateApplication — a candidate's application with AI screening + ML scores
  InterviewInvitation  — AI-generated invitation email + questions for a candidate
  InterviewFeedback    — post-interview ratings submitted by HR/HM
  AgentRun             — telemetry record for every OpenAI call
  MlPrediction         — persisted fit/join scores + SHAP explanations per run
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, SmallInteger, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentRun(Base):
    """One record per OpenAI agent invocation — for traceability and eval."""
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(String(50))        # jd_drafter | cv_screener | supervisor | job_poster
    operation: Mapped[str] = mapped_column(String(50))         # initial_draft | revision | chat | route | screen | post
    prompt_version: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))            # success | error

    # Links (both nullable — not every run belongs to a session or application)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Perf + cost
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)

    # Agent-specific eval metrics (flexible JSON)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class User(Base):
    """Application user — HR or Hiring Manager.

    email_hash   — SHA-256 blind index; used for fast lookup without decrypting.
    email_encrypted — Fernet ciphertext; decrypted only when the value is needed.
    hashed_password — bcrypt one-way hash; never stored in plain text.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)   # SHA-256 hex
    email_encrypted: Mapped[str] = mapped_column(Text)                              # Fernet token
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50))                                   # "hr" | "hm"
    hashed_password: Mapped[str] = mapped_column(String(255))                       # bcrypt
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class JobPosting(Base):
    """A platform-specific posting of an approved JD."""
    __tablename__ = "job_postings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jd_requests.id"))
    platform: Mapped[str] = mapped_column(String(50))            # "linkedin" | "indeed" | "google_jobs"
    formatted_content: Mapped[str] = mapped_column(Text)
    post_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="posted")  # "posted" | "failed"
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    request: Mapped["JDRequest"] = relationship("JDRequest", back_populates="postings")


class MlPrediction(Base):
    """One record per candidate per ML prediction query — persists fit/join scores and SHAP factors."""
    __tablename__ = "ml_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("candidate_applications.id", ondelete="CASCADE"), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    candidate_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prediction_type: Mapped[str] = mapped_column(String(10))            # fit | join | both
    fit_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    join_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    fit_explanation: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    join_explanation: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PastJD(Base):
    """Stores historical approved JDs used for RAG retrieval."""
    __tablename__ = "past_jds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    department: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)  # full JD text
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))  # text-embedding-3-small dims
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class JDRequest(Base):
    """A job requirement submission from HM/HR that kicks off the JD drafting flow."""
    __tablename__ = "jd_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, index=True)
    submitted_by: Mapped[str] = mapped_column(String(255))  # user id or email
    role: Mapped[str] = mapped_column(String(50))           # "hm" or "hr"

    title: Mapped[str] = mapped_column(String(255))
    department: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(255))
    salary_band: Mapped[str] = mapped_column(String(100))
    required_skills: Mapped[list[str]] = mapped_column(JSON)
    nice_to_have_skills: Mapped[list[str]] = mapped_column(JSON)
    company_description: Mapped[str] = mapped_column(Text)
    additional_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="drafting")  # drafting | pending_approval | approved | rejected | published
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_applications: Mapped[int | None] = mapped_column(nullable=True)

    drafts: Mapped[list["JDDraft"]] = relationship("JDDraft", back_populates="request", order_by="JDDraft.version")
    messages: Mapped[list["ChatMessage"]] = relationship("ChatMessage", back_populates="request", order_by="ChatMessage.created_at")
    postings: Mapped[list["JobPosting"]] = relationship("JobPosting", back_populates="request", order_by="JobPosting.posted_at")
    applications: Mapped[list["CandidateApplication"]] = relationship("CandidateApplication", back_populates="request", order_by="CandidateApplication.applied_at")


class JDDraft(Base):
    """Each iteration of the AI-generated JD draft."""
    __tablename__ = "jd_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jd_requests.id"))
    version: Mapped[int] = mapped_column(default=1)
    content: Mapped[str] = mapped_column(Text)
    rejection_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "jd-v1"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    request: Mapped["JDRequest"] = relationship("JDRequest", back_populates="drafts")


class ChatMessage(Base):
    """Chat history for a JD drafting session."""
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jd_requests.id"))
    role: Mapped[str] = mapped_column(String(20))   # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    request: Mapped["JDRequest"] = relationship("JDRequest", back_populates="messages")


class CandidateApplication(Base):
    """A candidate's application for a published job, with AI screening results."""
    __tablename__ = "candidate_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jd_requests.id"))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # CV file
    cv_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cv_path: Mapped[str | None] = mapped_column(String(500), nullable=True)   # server-side path

    # AI screening
    screening_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | screened | failed
    screening_score: Mapped[int | None] = mapped_column(nullable=True)             # 0–100
    screening_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    screening_strengths: Mapped[list | None] = mapped_column(JSON, nullable=True)
    screening_gaps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    screening_recommendation: Mapped[str | None] = mapped_column(String(50), nullable=True)  # strong_match | good_match | partial_match | poor_match
    screening_prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "screen-v1"

    # Interview scheduling
    shortlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    interview_status: Mapped[str | None] = mapped_column(String(20), nullable=True)       # scheduled | completed | cancelled
    interview_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interview_format: Mapped[str | None] = mapped_column(String(20), nullable=True)       # phone | video | in_person
    interview_location: Mapped[str | None] = mapped_column(String(500), nullable=True)    # URL or physical address
    interview_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # ML outcome labels — recorded by HR after a hiring decision is made
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)                   # hired | rejected | withdrew | no_hire
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Offer stage — recorded by HR; target labels for join prediction model
    offer_extended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    offer_amount: Mapped[str | None] = mapped_column(String(100), nullable=True)             # free-text, e.g. "£55,000"
    offer_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    offer_declined_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)     # competing_offer | salary | role_fit | location | other

    # Extra signal for join prediction features
    interview_rounds: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)        # total rounds completed
    days_to_respond: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)         # days between invite sent and candidate reply

    request: Mapped["JDRequest"] = relationship("JDRequest", back_populates="applications")
    invitations: Mapped[list["InterviewInvitation"]] = relationship("InterviewInvitation", back_populates="application", order_by="InterviewInvitation.created_at")
    feedback: Mapped[list["InterviewFeedback"]] = relationship("InterviewFeedback", back_populates="application", order_by="InterviewFeedback.created_at")


class InterviewInvitation(Base):
    """AI-generated interview invitation email + tailored questions for a shortlisted candidate."""
    __tablename__ = "interview_invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidate_applications.id"), index=True)

    # AI-generated draft (immutable after creation)
    email_subject: Mapped[str] = mapped_column(String(500))
    email_body: Mapped[str] = mapped_column(Text)
    interview_questions: Mapped[list[str]] = mapped_column(JSON)

    # HR-approved final version (set when HR clicks Approve & Send)
    final_recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    final_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    final_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_send_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    application: Mapped["CandidateApplication"] = relationship("CandidateApplication", back_populates="invitations")


class InterviewFeedback(Base):
    """Post-interview feedback submitted by HR/HM after the interview is conducted."""
    __tablename__ = "interview_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidate_applications.id", ondelete="CASCADE"), index=True)
    submitted_by: Mapped[str] = mapped_column(String(255))                          # user name or email
    round: Mapped[int] = mapped_column(SmallInteger, default=1)                     # interview round number
    overall_rating: Mapped[int] = mapped_column(SmallInteger)                       # 1–5
    technical_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    communication_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    cultural_fit_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    strengths: Mapped[str | None] = mapped_column(Text, nullable=True)
    concerns: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(20))                         # strong_hire | hire | no_hire | strong_no_hire
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    application: Mapped["CandidateApplication"] = relationship("CandidateApplication", back_populates="feedback")
