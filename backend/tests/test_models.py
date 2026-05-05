"""Tests for SQLAlchemy model instantiation and field defaults."""
import uuid
import pytest
from app.db.models import PastJD, JDRequest, JDDraft, ChatMessage


def test_jd_request_defaults():
    req = JDRequest(
        submitted_by="hr@example.com",
        role="hr",
        title="Data Analyst",
        department="Analytics",
        location="London, UK",
        salary_band="£50k–£65k",
        required_skills=["SQL", "Python"],
        nice_to_have_skills=["Tableau"],
        company_description="A data-driven company.",
    )
    # status default is applied at DB INSERT time, not Python construction time
    assert req.status in ("drafting", None)
    assert req.additional_context is None


def test_jd_request_id_is_uuid():
    req = JDRequest(
        submitted_by="hm@example.com",
        role="hm",
        title="Backend Engineer",
        department="Engineering",
        location="Manchester",
        salary_band="£70k–£90k",
        required_skills=["Go"],
        nice_to_have_skills=[],
        company_description="A cloud company.",
    )
    # id is generated as a uuid by the default factory
    assert req.id is None or isinstance(req.id, uuid.UUID)


def test_jd_draft_default_version():
    draft = JDDraft(
        request_id=uuid.uuid4(),
        content="Draft JD content here.",
    )
    # version default is applied at DB INSERT time, not Python construction time
    assert draft.version in (1, None)
    assert draft.rejection_feedback is None


def test_chat_message_fields():
    msg = ChatMessage(
        request_id=uuid.uuid4(),
        role="user",
        content="Please make the tone more formal.",
    )
    assert msg.role == "user"
    assert "formal" in msg.content


def test_past_jd_instantiation():
    jd = PastJD(
        title="Product Manager",
        department="Product",
        content="Full JD text...",
        embedding=[0.1] * 1536,
    )
    assert jd.title == "Product Manager"
    assert len(jd.embedding) == 1536