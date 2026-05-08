"""
Tests for POST /api/ml/predict and POST /api/candidates/applications/{id}/outcome.

All DB and OpenAI calls are mocked — no real network required.
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock

import pytest
from httpx import AsyncClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_application(outcome=None, offer_accepted=None):
    app = MagicMock()
    app.id = uuid.uuid4()
    app.name = "Alice Smith"
    app.email = "alice@example.com"
    app.phone = "+44 7700 900000"
    app.cover_letter = "I am excited about this role."
    app.cv_filename = "alice_cv.pdf"
    app.cv_path = "/uploads/alice_cv.pdf"
    app.screening_status = "screened"
    app.screening_score = 82
    app.screening_summary = "Strong Python background."
    app.screening_strengths = ["Python", "FastAPI"]
    app.screening_gaps = []
    app.screening_recommendation = "strong_match"
    app.applied_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    app.shortlisted = True
    app.interview_status = "scheduled"
    app.interview_scheduled_at = None
    app.interview_format = "video"
    app.interview_location = None
    app.interview_notes = None
    app.outcome = outcome
    app.outcome_recorded_at = None
    app.offer_extended = None
    app.offer_amount = None
    app.offer_date = None
    app.offer_accepted = offer_accepted
    app.offer_declined_reason = None
    app.interview_rounds = 2
    app.days_to_respond = 3
    app.request_id = uuid.uuid4()
    return app


def _auth_headers():
    """Fake JWT header — auth middleware is bypassed via dependency override in conftest."""
    return {"Authorization": "Bearer test-token"}


# ── POST /api/ml/predict ──────────────────────────────────────────────────────

class TestMlPredictEndpoint:
    @pytest.mark.asyncio
    async def test_returns_streaming_ndjson(self, client: AsyncClient, db_session):
        """Endpoint streams NDJSON — response must be parseable line by line."""
        async def _fake_stream(*args, **kwargs):
            yield json.dumps({"type": "results", "data": []}) + "\n"
            yield json.dumps({"type": "chunk", "text": "No candidates found."}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"

        with patch("app.api.routes.ml.agent6_predict", side_effect=_fake_stream):
            resp = await client.post(
                "/api/ml/predict",
                json={"question": "What is the fit score for all candidates?"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        assert "ndjson" in resp.headers.get("content-type", "")

        lines = [l for l in resp.text.strip().split("\n") if l]
        assert len(lines) == 3
        types = [json.loads(l)["type"] for l in lines]
        assert types == ["results", "chunk", "done"]

    @pytest.mark.asyncio
    async def test_requires_auth(self, unauth_client: AsyncClient):
        resp = await unauth_client.post(
            "/api/ml/predict",
            json={"question": "rank candidates by fit"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_question_field_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/api/ml/predict",
            json={"session_id": str(uuid.uuid4())},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_optional_session_id_accepted(self, client: AsyncClient):
        session_id = str(uuid.uuid4())

        async def _fake_stream(*args, **kwargs):
            yield json.dumps({"type": "results", "data": []}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"

        with patch("app.api.routes.ml.agent6_predict", side_effect=_fake_stream):
            resp = await client.post(
                "/api/ml/predict",
                json={"question": "join probability for this role", "session_id": session_id},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_error_chunk_propagated(self, client: AsyncClient):
        async def _error_stream(*args, **kwargs):
            yield json.dumps({"type": "error", "message": "Model not loaded"}) + "\n"

        with patch("app.api.routes.ml.agent6_predict", side_effect=_error_stream):
            resp = await client.post(
                "/api/ml/predict",
                json={"question": "fit scores"},
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        lines = [l for l in resp.text.strip().split("\n") if l]
        parsed = [json.loads(l) for l in lines]
        assert any(p["type"] == "error" for p in parsed)


# ── POST /api/candidates/applications/{id}/outcome ────────────────────────────

class TestOutcomeEndpoint:
    @pytest.mark.asyncio
    async def test_records_hired_outcome(self, client: AsyncClient, db_session):
        app = _make_application()
        db_session.execute.return_value.scalar_one_or_none.return_value = app

        resp = await client.post(
            f"/api/candidates/applications/{app.id}/outcome",
            json={"outcome": "hired"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        assert resp.json()["outcome"] == "hired"

    @pytest.mark.asyncio
    async def test_records_full_offer_details(self, client: AsyncClient, db_session):
        app = _make_application()
        db_session.execute.return_value.scalar_one_or_none.return_value = app

        resp = await client.post(
            f"/api/candidates/applications/{app.id}/outcome",
            json={
                "outcome": "hired",
                "offer_extended": True,
                "offer_amount": "£65,000",
                "offer_accepted": True,
                "offer_declined_reason": None,
                "interview_rounds": 3,
                "days_to_respond": 2,
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        assert app.offer_extended is True
        assert app.offer_amount == "£65,000"
        assert app.offer_accepted is True
        assert app.interview_rounds == 3
        assert app.days_to_respond == 2

    @pytest.mark.asyncio
    async def test_records_rejected_outcome(self, client: AsyncClient, db_session):
        app = _make_application()
        db_session.execute.return_value.scalar_one_or_none.return_value = app

        resp = await client.post(
            f"/api/candidates/applications/{app.id}/outcome",
            json={"outcome": "rejected"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        assert app.outcome == "rejected"

    @pytest.mark.asyncio
    async def test_records_withdrew_outcome(self, client: AsyncClient, db_session):
        app = _make_application()
        db_session.execute.return_value.scalar_one_or_none.return_value = app

        resp = await client.post(
            f"/api/candidates/applications/{app.id}/outcome",
            json={"outcome": "withdrew"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_outcome_returns_400(self, client: AsyncClient, db_session):
        app = _make_application()
        db_session.execute.return_value.scalar_one_or_none.return_value = app

        resp = await client.post(
            f"/api/candidates/applications/{app.id}/outcome",
            json={"outcome": "maybe"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400
        assert "outcome" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_unknown_application_returns_404(self, client: AsyncClient, db_session):
        db_session.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.post(
            f"/api/candidates/applications/{uuid.uuid4()}/outcome",
            json={"outcome": "hired"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_auth(self, unauth_client: AsyncClient):
        resp = await unauth_client.post(
            f"/api/candidates/applications/{uuid.uuid4()}/outcome",
            json={"outcome": "hired"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_offer_declined_reason_recorded(self, client: AsyncClient, db_session):
        app = _make_application()
        db_session.execute.return_value.scalar_one_or_none.return_value = app

        resp = await client.post(
            f"/api/candidates/applications/{app.id}/outcome",
            json={
                "outcome": "no_hire",
                "offer_extended": True,
                "offer_accepted": False,
                "offer_declined_reason": "competing_offer",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        assert app.offer_declined_reason == "competing_offer"
        assert app.offer_accepted is False

    @pytest.mark.asyncio
    async def test_outcome_recorded_at_is_set(self, client: AsyncClient, db_session):
        app = _make_application()
        db_session.execute.return_value.scalar_one_or_none.return_value = app

        await client.post(
            f"/api/candidates/applications/{app.id}/outcome",
            json={"outcome": "hired"},
            headers=_auth_headers(),
        )

        assert app.outcome_recorded_at is not None

    @pytest.mark.asyncio
    async def test_missing_outcome_field_returns_422(self, client: AsyncClient):
        resp = await client.post(
            f"/api/candidates/applications/{uuid.uuid4()}/outcome",
            json={"offer_extended": True},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422