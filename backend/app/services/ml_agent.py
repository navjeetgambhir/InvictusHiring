"""
ML Prediction Agent (Agent 6) — natural language interface to the fit and join-prediction models.

Given a plain-English question about candidate fit or offer acceptance, this agent:
  1. Uses OpenAI to extract intent (fit | join | both) and any filters (session, candidate name)
  2. Fetches matching CandidateApplication + JDRequest rows from the DB
  3. Runs predict_fit() / predict_join() from ml_predictor.py
  4. Streams a natural language summary as NDJSON

Streams NDJSON lines:
  {"type": "chunk",    "text": "..."}
  {"type": "results",  "data": [...]}   — structured predictions for UI rendering
  {"type": "done"}
  {"type": "error",    "message": "..."}

Example queries
---------------
  "What is the fit score for all candidates in the senior engineer role?"
  "Which shortlisted candidates are most likely to accept an offer?"
  "Show me join probability for Alice Johnson"
  "Rank candidates by fit for session abc-123"
"""

import json
import time
import uuid
from typing import AsyncIterator

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import CandidateApplication, JDRequest
from app.services.ml_predictor import predict_fit, predict_join, explain_fit, explain_join
from app.services.agent_telemetry import fire_run
import asyncio

_client = AsyncOpenAI(api_key=settings.openai_api_key)

ML_AGENT_PROMPT_VERSION = "ml-agent-v1"

_PARSE_SYSTEM = """You are a query parser for an ML prediction service in a hiring platform.

Extract from the user's question:
1. prediction_type: "fit" | "join" | "both"
   - "fit" = candidate-to-role fit probability
   - "join" = offer acceptance probability
   - "both" = user wants both scores
2. session_id: UUID string if the user mentions a specific session/job, else null
3. candidate_name: partial name string if the user mentions a specific candidate, else null
4. shortlisted_only: true if the user only wants shortlisted candidates, else false
5. sort_by: "fit" | "join" | "name" | null — how to sort results

Return ONLY a JSON object with these five fields. No explanation."""

_SUMMARISE_SYSTEM = """You are a concise HR analytics assistant.

Given a list of ML prediction results for candidates — including fit score, join probability, and key SHAP factors — write a brief natural language summary.
- Lead with the headline insight (top candidate, score range, notable pattern)
- Mention 2–3 specific candidates by name with their scores and 1–2 key factors driving the score
- Note any candidates with high fit but low join probability (flight risk / competing offers)
- Reference specific factors naturally, e.g. "driven mainly by strong skill match" or "held back by skill gaps"
- IMPORTANT: each factor shows its actual value (e.g. cover_letter_words=absent/zero). If a factor value is absent/zero, say the candidate LACKED that signal — never describe an absent feature as present or strong. A positive SHAP contribution from an absent feature means the model expected it to matter but it wasn't there, or that absence itself was informative in the training data — do NOT interpret it as a positive quality.
- Use plain English, no markdown tables
- Maximum 5 sentences"""


async def _parse_query(question: str) -> dict:
    """Use OpenAI to extract structured intent from the user's natural language question."""
    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _PARSE_SYSTEM},
            {"role": "user", "content": question},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content or "{}")


async def _fetch_applications(
    db: AsyncSession,
    session_id: str | None,
    candidate_name: str | None,
    shortlisted_only: bool,
) -> list[tuple[CandidateApplication, JDRequest]]:
    """Query DB for applications matching the parsed filters."""
    q = (
        select(CandidateApplication, JDRequest)
        .join(JDRequest, CandidateApplication.request_id == JDRequest.id)
        .where(JDRequest.status == "published")
    )

    if session_id:
        try:
            sid = uuid.UUID(session_id)
            q = q.where(JDRequest.session_id == sid)
        except ValueError:
            pass

    if shortlisted_only:
        q = q.where(CandidateApplication.shortlisted == True)  # noqa: E712

    if candidate_name:
        q = q.where(CandidateApplication.name.ilike(f"%{candidate_name}%"))

    rows = (await db.execute(q)).all()
    return rows


async def stream_ml_predictions(
    question: str,
    db: AsyncSession,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Parse the question, run ML predictions, and stream NDJSON results.
    session_id can be passed directly from the route context to narrow the query.
    """
    t0 = time.perf_counter()
    status = "success"
    error_message = None
    input_tokens = output_tokens = None
    prediction_type = "both"
    candidate_count = 0
    shap_count = 0

    try:
        # ── 1. Parse the user's question ──────────────────────────────────────
        parsed = await _parse_query(question)
        prediction_type = parsed.get("prediction_type", "both")
        filter_session = parsed.get("session_id") or session_id
        filter_name = parsed.get("candidate_name")
        shortlisted_only = bool(parsed.get("shortlisted_only", False))
        sort_by = parsed.get("sort_by") or prediction_type

        logger.info(
            f"ML agent | parsed | type={prediction_type} session={filter_session} "
            f"candidate={filter_name} shortlisted_only={shortlisted_only}"
        )

        # ── 2. Fetch applications ──────────────────────────────────────────────
        rows = await _fetch_applications(db, filter_session, filter_name, shortlisted_only)

        if not rows:
            yield json.dumps({"type": "chunk", "text": "No matching candidates found for your query."}) + "\n"
            yield json.dumps({"type": "results", "data": []}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
            return

        # ── 3. Run predictions + SHAP explanations ────────────────────────────
        results = []
        for app, job in rows:
            row = {
                "application_id": str(app.id),
                "candidate_name": app.name,
                "job_title": job.title,
                "session_id": str(job.session_id),
                "screening_score": app.screening_score,
                "screening_recommendation": app.screening_recommendation,
                "shortlisted": app.shortlisted,
            }
            if prediction_type in ("fit", "both"):
                row["fit_probability"] = predict_fit(app, job)
                row["fit_explanation"] = explain_fit(app, job, top_n=5)
            if prediction_type in ("join", "both"):
                row["join_probability"] = predict_join(app, job)
                row["join_explanation"] = explain_join(app, job, top_n=5)
            results.append(row)

        # ── 4. Sort ────────────────────────────────────────────────────────────
        def _sort_key(r):
            if sort_by == "fit":
                return r.get("fit_probability") or 0
            if sort_by == "join":
                return r.get("join_probability") or 0
            return r.get("candidate_name", "")

        results.sort(key=_sort_key, reverse=(sort_by != "name"))

        candidate_count = len(results)
        shap_count = sum(
            1 for r in results
            if r.get("fit_explanation") or r.get("join_explanation")
        )

        # ── 5. Emit structured results first (UI can render immediately) ───────
        yield json.dumps({"type": "results", "data": results}) + "\n"

        # ── 6. Generate and stream a natural language summary ─────────────────
        def _top_factors_text(explanation: list[dict]) -> str:
            if not explanation:
                return "no explanation available"
            parts = []
            for f in explanation[:3]:
                arrow = "↑" if f["direction"] == "positive" else "↓"
                raw = f["raw_value"]
                # Represent the actual value clearly so the LLM can't misread absence as presence
                if raw == 0:
                    val_str = "absent/zero"
                elif raw == 1 and f["feature"].startswith(("has_", "was_", "reached_", "interview_format_")):
                    val_str = "present"
                else:
                    val_str = str(round(raw, 2))
                parts.append(f"{f['label']}={val_str} ({arrow}{abs(f['contribution']):.3f})")
            return ", ".join(parts)

        results_text = "\n".join(
            f"- {r['candidate_name']} | {r['job_title']} | "
            f"fit={r.get('fit_probability', 'N/A')}% | "
            f"join={r.get('join_probability', 'N/A')}% | "
            f"score={r.get('screening_score', 'N/A')} | "
            f"shortlisted={r['shortlisted']} | "
            f"fit_key_factors=[{_top_factors_text(r.get('fit_explanation', []))}] | "
            f"join_key_factors=[{_top_factors_text(r.get('join_explanation', []))}]"
            for r in results
        )
        summary_prompt = (
            f"User asked: {question}\n\n"
            f"Prediction type: {prediction_type}\n"
            f"Candidates ({len(results)} total):\n{results_text}"
        )

        summary_response = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SUMMARISE_SYSTEM},
                {"role": "user", "content": summary_prompt},
            ],
            temperature=0.4,
            stream=True,
        )

        async for chunk in summary_response:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield json.dumps({"type": "chunk", "text": delta}) + "\n"

        if prediction_type in ("fit", "join", "both") and any(
            r.get("fit_probability") is None and r.get("join_probability") is None
            for r in results
        ):
            yield json.dumps({
                "type": "chunk",
                "text": "\n\n⚠ ML models have not been trained yet. Run `python backend/ml_train.py` to generate predictions.",
            }) + "\n"

        yield json.dumps({"type": "done"}) + "\n"

    except Exception as exc:
        logger.error(f"ML agent error: {exc}")
        status = "error"
        error_message = str(exc)
        yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        asyncio.create_task(fire_run(
            agent_name="ml_predictor",
            operation="predict",
            prompt_version=ML_AGENT_PROMPT_VERSION,
            model=settings.openai_model,
            status=status,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metrics={
                "question_length": len(question),
                "prediction_type": prediction_type,
                "candidate_count": candidate_count,
                "shap_explanations": shap_count,
            },
            error_message=error_message,
        ))