from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.supervisor import supervisor_classify, supervisor_route, agent4_query

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class ClassifyRequest(BaseModel):
    message: str
    pipeline_state: str = "idle"
    has_draft: bool = False


class RouteRequest(BaseModel):
    message: str
    pipeline_state: str = "idle"
    has_draft: bool = False
    history: list[dict] = []


class QueryRequest(BaseModel):
    question: str


@router.post("/classify")
async def classify(
    body: ClassifyRequest,
    _user: CurrentUser = Depends(get_current_user),
):
    """Simple 3-value intent: jd_draft | analytics | other."""
    intent = await supervisor_classify(body.message)
    return {"intent": intent}


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
        agent4_query(body.question, db),
        media_type="application/x-ndjson",
    )