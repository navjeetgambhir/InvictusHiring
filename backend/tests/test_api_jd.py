"""Integration-style tests for the JD API routes (no real DB or OpenAI)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import JDRequest, JDDraft, ChatMessage


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_jd_request(session_id: uuid.UUID | None = None, status: str = "pending_approval") -> JDRequest:
    req = JDRequest(
        submitted_by="hr@example.com",
        role="hr",
        title="Software Engineer",
        department="Engineering",
        location="London, UK",
        salary_band="£60k–£80k",
        required_skills=["Python"],
        nice_to_have_skills=[],
        company_description="A tech company.",
    )
    req.id = uuid.uuid4()
    req.session_id = session_id or uuid.uuid4()
    req.status = status
    return req


def _mock_draft(request_id: uuid.UUID, version: int = 1) -> JDDraft:
    draft = JDDraft(request_id=request_id, content="Draft JD content.", version=version)
    draft.id = uuid.uuid4()
    return draft


async def _fake_stream(*args, **kwargs):
    yield "chunk1"
    yield " chunk2"


# ── GET /health ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── POST /api/jd/draft-freetext ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_freetext_draft_streams_content(client, db_session):
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    extracted = {
        "title": "Backend Engineer", "department": "Engineering",
        "location": "London", "salary_band": "£70k",
        "required_skills": ["Python"], "nice_to_have_skills": [],
        "company_description": "A tech company.",
    }

    with (
        patch("app.api.routes.jd.extract_requirements", AsyncMock(return_value=extracted)),
        patch("app.api.routes.jd.stream_initial_draft", side_effect=_fake_stream),
    ):
        response = await client.post("/api/jd/draft-freetext", json={
            "submitted_by": "hm@example.com",
            "role": "hm",
            "text": "We need a Backend Engineer in London, £70k, must know Python.",
        })

    assert response.status_code == 200
    assert "chunk1" in response.text
    assert "__SESSION_ID__" in response.text


@pytest.mark.asyncio
async def test_freetext_draft_invalid_role_returns_422(client):
    response = await client.post("/api/jd/draft-freetext", json={
        "submitted_by": "hm@example.com",
        "role": "ceo",
        "text": "Need an engineer.",
    })
    assert response.status_code == 422


# ── POST /api/jd/draft ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_draft_streams_content(client, valid_requirements, db_session):
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    with patch("app.api.routes.jd.stream_initial_draft", side_effect=_fake_stream):
        response = await client.post("/api/jd/draft", json=valid_requirements)

    assert response.status_code == 200
    assert "chunk1" in response.text
    assert "chunk2" in response.text
    assert "__SESSION_ID__" in response.text


@pytest.mark.asyncio
async def test_create_draft_missing_required_skill_returns_422(client):
    bad_payload = {
        "submitted_by": "hr@example.com",
        "role": "hr",
        "title": "Engineer",
        "department": "Eng",
        "location": "London",
        "salary_band": "£60k",
        "required_skills": [],        # violates min_length=1
        "company_description": "Corp.",
    }
    response = await client.post("/api/jd/draft", json=bad_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_draft_invalid_role_returns_422(client, valid_requirements):
    valid_requirements["role"] = "ceo"  # not "hm" or "hr"
    response = await client.post("/api/jd/draft", json=valid_requirements)
    assert response.status_code == 422


# ── POST /api/jd/chat ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_streams_reply(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id)
    draft = _mock_draft(req.id)

    # First execute() → finds the JDRequest; second → finds the latest draft; third → chat history
    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=draft)),
        MagicMock(scalars=MagicMock(return_value=iter([]))),
    ]
    db_session.execute = AsyncMock(side_effect=results)

    with patch("app.api.routes.jd.stream_chat_reply", side_effect=_fake_stream):
        response = await client.post(
            "/api/jd/chat",
            json={"session_id": str(sample_session_id), "message": "Make it more formal"},
        )

    assert response.status_code == 200
    assert "chunk1" in response.text


@pytest.mark.asyncio
async def test_chat_returns_404_for_unknown_session(client, db_session):
    db_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    response = await client.post(
        "/api/jd/chat",
        json={"session_id": str(uuid.uuid4()), "message": "Hello"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


@pytest.mark.asyncio
async def test_chat_returns_400_when_no_draft_exists(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id)
    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),   # found request
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no draft
    ]
    db_session.execute = AsyncMock(side_effect=results)

    response = await client.post(
        "/api/jd/chat",
        json={"session_id": str(sample_session_id), "message": "Hello"},
    )
    assert response.status_code == 400
    assert "No draft" in response.json()["detail"]


# ── POST /api/jd/approve ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_sets_status_approved(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id)
    draft = _mock_draft(req.id)

    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=draft)),
    ]
    db_session.execute = AsyncMock(side_effect=results)

    response = await client.post(
        "/api/jd/approve",
        json={"session_id": str(sample_session_id), "approved": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["session_id"] == str(sample_session_id)
    assert req.status == "approved"


@pytest.mark.asyncio
async def test_reject_without_feedback_returns_422(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id)
    draft = _mock_draft(req.id)

    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=draft)),
    ]
    db_session.execute = AsyncMock(side_effect=results)

    response = await client.post(
        "/api/jd/approve",
        json={"session_id": str(sample_session_id), "approved": False},  # no feedback
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_with_feedback_streams_revision(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id)
    draft = _mock_draft(req.id)

    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=draft)),
        MagicMock(scalars=MagicMock(return_value=iter([]))),   # chat history
    ]
    db_session.execute = AsyncMock(side_effect=results)

    with patch("app.api.routes.jd.stream_revision", side_effect=_fake_stream):
        response = await client.post(
            "/api/jd/approve",
            json={
                "session_id": str(sample_session_id),
                "approved": False,
                "feedback": "Too generic, add more specifics.",
            },
        )

    assert response.status_code == 200
    assert "chunk1" in response.text


@pytest.mark.asyncio
async def test_approve_returns_404_for_unknown_session(client, db_session):
    db_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    response = await client.post(
        "/api/jd/approve",
        json={"session_id": str(uuid.uuid4()), "approved": True},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_returns_400_when_no_draft(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id)
    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no draft
    ]
    db_session.execute = AsyncMock(side_effect=results)

    response = await client.post(
        "/api/jd/approve",
        json={"session_id": str(sample_session_id), "approved": True},
    )
    assert response.status_code == 400


# ── GET /api/jd/session/{session_id} ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_session_returns_full_state(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id, status="pending_approval")
    draft = _mock_draft(req.id, version=2)
    msg = ChatMessage(request_id=req.id, role="user", content="Make it formal")

    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=draft)),
        MagicMock(scalars=MagicMock(return_value=iter([msg]))),
    ]
    db_session.execute = AsyncMock(side_effect=results)

    response = await client.get(f"/api/jd/session/{sample_session_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == str(sample_session_id)
    assert data["status"] == "pending_approval"
    assert data["latest_draft"] == "Draft JD content."
    assert data["draft_version"] == 2
    assert len(data["chat_history"]) == 1
    assert data["chat_history"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_get_session_returns_404_for_unknown(client, db_session):
    db_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    response = await client.get(f"/api/jd/session/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_session_no_draft_returns_null_fields(client, db_session, sample_session_id):
    req = _mock_jd_request(session_id=sample_session_id, status="drafting")
    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=req)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no draft yet
        MagicMock(scalars=MagicMock(return_value=iter([]))),
    ]
    db_session.execute = AsyncMock(side_effect=results)

    response = await client.get(f"/api/jd/session/{sample_session_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["latest_draft"] is None
    assert data["draft_version"] == 0