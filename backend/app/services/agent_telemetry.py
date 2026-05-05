"""
Agent telemetry — lightweight eval + traceability for every OpenAI call.

Usage
-----
    import time, asyncio
    from app.services.agent_telemetry import fire_run

    t0 = time.perf_counter()
    # ... do the OpenAI call ...
    asyncio.create_task(fire_run(
        agent_name="supervisor",
        operation="route",
        prompt_version=SUPERVISOR_PROMPT_VERSION,
        model="gpt-4o-mini",
        status="success",
        latency_ms=int((time.perf_counter() - t0) * 1000),
        session_id=session_id,
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        metrics={"intent": "jd_draft", "confidence": 0.95},
    ))

fire_run() opens its own DB session so it never interferes with the caller's
transaction. It is always fired as a background task so latency is zero.
"""
import uuid
from typing import Any

from loguru import logger

from app.core.database import AsyncSessionLocal
from app.db.models import AgentRun


async def fire_run(
    *,
    agent_name: str,
    operation: str,
    prompt_version: str,
    model: str,
    status: str,
    latency_ms: int | None = None,
    session_id: uuid.UUID | str | None = None,
    application_id: uuid.UUID | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    metrics: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """Persist one agent run record. Always call via asyncio.create_task()."""
    sid = uuid.UUID(str(session_id)) if session_id else None
    try:
        async with AsyncSessionLocal() as db:
            db.add(AgentRun(
                agent_name=agent_name,
                operation=operation,
                prompt_version=prompt_version,
                model=model,
                status=status,
                session_id=sid,
                application_id=application_id,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                metrics=metrics,
                error_message=error_message,
            ))
            await db.commit()
    except Exception as exc:
        logger.warning(f"agent_telemetry: failed to write run record — {exc}")