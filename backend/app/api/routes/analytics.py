"""
Analytics routes — context-aware message routing (supervisor) and NLP-to-SQL queries.

POST /analytics/route   — supervisor classifies the user's message and returns an intent decision
POST /analytics/query   — NLP→SQL analytics agent streams NDJSON results for HR data questions
"""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.supervisor import supervisor_route, agent4_query

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class RouteRequest(BaseModel):
    message: str
    pipeline_state: str = "idle"
    has_draft: bool = False
    history: list[dict[str, Any]] = []
    session_id: str | None = None
    job_title: str | None = None
    job_department: str | None = None


class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None


@router.post("/route")
async def route(
    body: RouteRequest,
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Context-aware routing decision.
    Returns intent, confidence, reasoning, suggested_action, secondary_intent.
    """
    decision = await supervisor_route(
        message=body.message,
        pipeline_state=body.pipeline_state,
        history=body.history or [],
        has_draft=body.has_draft,
        job_title=body.job_title,
        job_department=body.job_department,
    )
    return {
        "intent": decision.intent,
        "confidence": decision.confidence,
        "reasoning": decision.reasoning,
        "suggested_action": decision.suggested_action,
        "secondary_intent": decision.secondary_intent,
    }


@router.post("/query")
async def analytics_query(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """NLP→SQL agent — streams NDJSON: sql | chunk | done | error."""
    return StreamingResponse(
        agent4_query(body.question, db, session_id=body.session_id),
        media_type="application/x-ndjson",
    )