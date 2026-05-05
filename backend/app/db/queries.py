import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JDDraft, JDRequest


async def get_request_or_404(session_id: uuid.UUID, db: AsyncSession) -> JDRequest:
    result = await db.execute(select(JDRequest).where(JDRequest.session_id == session_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Session not found")
    return req


async def latest_draft(request_id: uuid.UUID, db: AsyncSession) -> JDDraft | None:
    result = await db.execute(
        select(JDDraft)
        .where(JDDraft.request_id == request_id)
        .order_by(JDDraft.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()