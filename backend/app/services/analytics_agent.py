"""Supervisor + NLP-to-SQL analytics agent for HR/HM queries."""
import asyncio
import json
import re
import time
import uuid
from typing import AsyncIterator

from loguru import logger
from openai import AsyncOpenAI
from langsmith import traceable
from langsmith.wrappers import wrap_openai
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JDRequest
from app.services.sql_ast_validator import validate_sql
from app.services.agent_telemetry import fire_run

ANALYTICS_PROMPT_VERSION = "analytics-v1"

_client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))

# ── DB schema fed to the SQL generator ────────────────────────────────────────

_DB_SCHEMA = """
PostgreSQL schema for the Invictus Hiring platform:

TABLE jd_requests (
  id UUID PRIMARY KEY,
  session_id UUID,
  submitted_by VARCHAR,       -- user id
  role VARCHAR,               -- 'hr' | 'hm'
  title VARCHAR,              -- job title
  department VARCHAR,
  location VARCHAR,
  salary_band VARCHAR,
  required_skills JSON,       -- string array
  nice_to_have_skills JSON,   -- string array
  company_description TEXT,
  status VARCHAR,             -- drafting | pending_approval | approved | rejected | published
  published_at TIMESTAMPTZ,   -- when the job was published (NULL if not yet published)
  expires_at TIMESTAMPTZ,     -- application deadline (NULL = no deadline)
  max_applications INT,       -- application cap (NULL = unlimited)
  created_at TIMESTAMPTZ
)

TABLE jd_drafts (
  id UUID PRIMARY KEY,
  request_id UUID REFERENCES jd_requests(id),
  version INT,
  content TEXT,
  rejection_feedback TEXT,
  created_at TIMESTAMPTZ
)

TABLE chat_messages (
  id UUID PRIMARY KEY,
  request_id UUID REFERENCES jd_requests(id),
  role VARCHAR,   -- 'user' | 'assistant'
  content TEXT,
  created_at TIMESTAMPTZ
)

TABLE job_postings (
  id UUID PRIMARY KEY,
  request_id UUID REFERENCES jd_requests(id),
  platform VARCHAR,    -- 'linkedin' | 'indeed' | 'google_jobs'
  formatted_content TEXT,
  post_url VARCHAR,
  status VARCHAR,      -- 'posted' | 'failed'
  posted_at TIMESTAMPTZ
)

TABLE candidate_applications (
  id UUID PRIMARY KEY,
  request_id UUID REFERENCES jd_requests(id),
  name VARCHAR,
  email VARCHAR,
  phone VARCHAR,
  cover_letter TEXT,
  cv_filename VARCHAR,
  screening_status VARCHAR,       -- 'pending' | 'screened' | 'failed'
  screening_score INT,            -- 0–100
  screening_summary TEXT,
  screening_strengths JSONB,      -- string array
  screening_gaps JSONB,           -- string array
  screening_recommendation VARCHAR,  -- 'strong_match' | 'good_match' | 'partial_match' | 'poor_match'
  applied_at TIMESTAMPTZ
)

TABLE users (
  id UUID PRIMARY KEY,
  name VARCHAR,
  role VARCHAR,   -- 'hr' | 'hm'
  created_at TIMESTAMPTZ
)
"""

# ── Supervisor ─────────────────────────────────────────────────────────────────

_SUPERVISOR_SYSTEM = (
    "You are a routing classifier for an HR platform. "
    "Classify the user message into exactly one category:\n"
    "- jd_draft: requests to create, write, draft, or edit a job description\n"
    "- analytics: questions about data, status, counts, applications, candidates, reports, history\n"
    "- other: greetings, thanks, or anything unrelated to hiring\n\n"
    "Reply with exactly one word: jd_draft, analytics, or other."
)


@traceable(name="analytics.classify_intent", run_type="chain", tags=["agent4", "analytics"])
async def classify_intent(message: str) -> str:
    response = await _client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SUPERVISOR_SYSTEM},
            {"role": "user", "content": message},
        ],
        temperature=0,
        max_tokens=5,
    )
    return (response.choices[0].message.content or "other").strip().lower()


# ── NLP→SQL agent ──────────────────────────────────────────────────────────────

_SQL_SYSTEM = f"""You are a PostgreSQL expert for an HR hiring platform.
Generate a safe, read-only SELECT query to answer the user's question.

{_DB_SCHEMA}

Rules:
- Only generate SELECT statements. Never write INSERT, UPDATE, DELETE, DROP, or DDL.
- Limit to 50 rows unless the user asks for more.
- For JSON/JSONB array columns use jsonb_array_elements_text() when needed.
- Return ONLY the raw SQL — no explanation, no markdown fences.

Domain rules (always apply these):
- "open positions", "live jobs", "active roles", "published jobs", or any question about the current job board
  MUST filter: WHERE jd_requests.status = 'published'
- Never count drafts, pending_approval, or approved jobs as "open" unless explicitly asked.
- If asked about a specific job and no session context is injected, match by title using ILIKE.
"""

_FORMAT_SYSTEM = """You are a helpful, friendly HR assistant — think of a knowledgeable colleague, not a database report.
Given the user's question and the query results, give a short, natural answer in plain conversational English.

Guidelines:
- Sound like a person, not a system. Write how a helpful colleague would explain results over Slack.
- Use specific numbers and names from the results.
- If there are multiple items, use bullet points.
- If the result is zero or empty, say so plainly and offer one practical thought — keep it brief, not a lecture.
- Keep answers under 150 words.
- NEVER mention UUIDs, internal IDs, request_id, session_id, or raw database identifiers.
  Refer to jobs by title and candidates by name only.
- Avoid corporate filler like "associated with the specified request", "a variety of reasons", "it could be due to".
"""

_UUID_RE = re.compile(
    r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(
    r"'[^']*@[^']*'",   # email literals inside SQL single-quotes
    re.IGNORECASE,
)
_EMAIL_PLAIN_RE = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
)


def _sanitise_output(text: str) -> str:
    """Strip UUID and email leakage from AI-generated narrative."""
    text = _UUID_RE.sub('[id]', text)
    text = _EMAIL_PLAIN_RE.sub('[email]', text)
    return text


def _sanitise_sql_for_display(sql: str) -> str:
    """
    Redact sensitive literals from SQL before showing it in the UI.
    UUIDs injected as session context and any email literals are replaced
    with safe placeholders — the actual executed SQL is unaffected.
    """
    sql = _UUID_RE.sub("'[id]'", sql)
    sql = _EMAIL_RE.sub("'[email]'", sql)
    return sql


async def _resolve_session_context(session_id: str | None, db: AsyncSession) -> str:
    """Return a context hint for the SQL prompt when a session is active."""
    if not session_id:
        return ""
    try:
        result = await db.execute(
            select(JDRequest).where(JDRequest.session_id == uuid.UUID(session_id))
        )
        req = result.scalar_one_or_none()
        if req:
            return (
                f"\n\nACTIVE SESSION CONTEXT:\n"
                f"The user is currently viewing the JD session with:\n"
                f"  session_id = '{session_id}'\n"
                f"  jd_requests.id = '{req.id}'\n"
                f"  title = '{req.title}'\n"
                f"When the user says 'this job', 'this role', or 'this position', "
                f"filter by request_id = '{req.id}' (UUID literal, no quotes needed in SQL cast)."
            )
    except Exception as exc:
        logger.warning(f"Analytics: could not resolve session context | {exc}")
    return ""


@traceable(name="analytics.nlp_to_sql", run_type="chain", tags=["agent4", "analytics"])
async def stream_analytics_response(question: str, db: AsyncSession, session_id: str | None = None) -> AsyncIterator[str]:
    """Classify → generate SQL → AST-validate → execute → stream NL answer as NDJSON."""
    t0 = time.perf_counter()
    status = "success"
    error_message = None
    sql_passed = False
    rows_returned = 0
    sql_blocked_reason: str | None = None
    input_tokens = output_tokens = None

    try:
        session_context = await _resolve_session_context(session_id, db)

        # Step 1: generate SQL
        sql_resp = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SQL_SYSTEM + session_context},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        raw_sql = (sql_resp.choices[0].message.content or "").strip()
        sql = raw_sql.replace("```sql", "").replace("```", "").strip()
        if sql_resp.usage:
            input_tokens = sql_resp.usage.prompt_tokens

        # Step 2: AST validation
        validation = validate_sql(sql)
        display_sql = _sanitise_sql_for_display(validation.normalized_sql or sql)
        yield json.dumps({"type": "sql", "sql": display_sql}) + "\n"

        if not validation.passed:
            sql_blocked_reason = validation.failure_reason
            status = "blocked"
            yield json.dumps({
                "type": "error",
                "message": f"Query blocked by safety validator: {validation.failure_reason}",
            }) + "\n"
            return

        sql_passed = True
        safe_sql = validation.normalized_sql or sql

        # Step 3: execute
        try:
            result = await db.execute(text(safe_sql))
            columns = list(result.keys())
            rows = result.fetchmany(50)
            data = [dict(zip(columns, row)) for row in rows]
            rows_returned = len(data)
            logger.info(f"Analytics query returned {rows_returned} rows | sql={safe_sql[:120]}")
        except Exception as exc:
            logger.error(f"Analytics SQL error: {exc} | sql={safe_sql}")
            status = "sql_error"
            error_message = str(exc)
            yield json.dumps({"type": "error", "message": f"Query failed: {exc}"}) + "\n"
            return

        # Step 4: stream NL answer
        prompt = (
            f"Question: {question}\n\n"
            f"SQL:\n{safe_sql}\n\n"
            f"Results ({rows_returned} rows):\n"
            f"{json.dumps(data[:20], indent=2, default=str)}"
        )
        stream = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _FORMAT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            stream_options={"include_usage": True},
            temperature=0.3,
        )
        async for chunk in stream:
            if chunk.usage:
                output_tokens = chunk.usage.completion_tokens
                continue
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield json.dumps({"type": "chunk", "text": _sanitise_output(delta)}) + "\n"

        yield json.dumps({"type": "done"}) + "\n"

    except Exception as exc:
        status = "error"
        error_message = str(exc)
        raise

    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        asyncio.create_task(fire_run(
            agent_name="analytics",
            operation="nlp_to_sql",
            prompt_version=ANALYTICS_PROMPT_VERSION,
            model=settings.openai_model,
            status=status,
            latency_ms=latency_ms,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metrics={
                "question_length": len(question),
                "sql_passed_validation": sql_passed,
                "sql_blocked_reason": sql_blocked_reason,
                "rows_returned": rows_returned,
                "has_session_context": bool(session_id),
            },
            error_message=error_message,
        ))
