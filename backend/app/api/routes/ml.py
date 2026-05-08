"""ML prediction agent routes — HR/HM only (requires JWT auth)."""
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.supervisor import agent6_predict

router = APIRouter(prefix="/ml", tags=["ML Predictions"])


class PredictRequest(BaseModel):
    question: str
    session_id: str | None = None   # narrow results to a specific JD session


@router.post("/predict")
async def predict(
    body: PredictRequest,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Agent 6 — ML fit and join-prediction queries.

    Accepts a plain-English question and streams NDJSON:
      {"type": "results", "data": [...]}   — structured predictions per candidate
      {"type": "chunk",   "text": "..."}   — natural language summary (streaming)
      {"type": "done"}

    Example questions:
    - "What is the fit score for all candidates in this role?"
    - "Which shortlisted candidates are most likely to accept an offer?"
    - "Rank candidates by join probability for session <uuid>"
    """
    return StreamingResponse(
        agent6_predict(body.question, db, session_id=body.session_id),
        media_type="application/x-ndjson",
    )