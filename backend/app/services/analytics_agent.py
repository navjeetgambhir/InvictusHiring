"""
Analytics Agent (Agent 4) — NLP-to-SQL query pipeline with AST safety validation.

Given a plain-English HR question this agent:
  1. Introspects the live database schema (once per process, cached)
  2. Uses OpenAI to generate a safe read-only SELECT statement
  3. Validates the SQL via an AST walk (sqlglot) before execution
  4. Executes the query via the MCP client (falls back to SQLAlchemy)
  5. Streams a natural language answer as NDJSON chunks

Safety layers:
  - AST validator blocks non-SELECT statements, dangerous functions, unknown tables
  - Output sanitiser strips UUID and email patterns from the narrated answer
  - SQL display sanitiser redacts UUIDs/emails from the badge shown in the UI
    (the SQL that is actually executed is never modified)
"""

import asyncio
import json
import re
import time
import uuid
from typing import AsyncIterator

from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from langsmith import traceable
from langsmith.wrappers import wrap_openai
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core import mcp_client
from app.db.models import JDRequest
from app.services.sql_ast_validator import validate_sql
from app.services.agent_telemetry import fire_run

ANALYTICS_PROMPT_VERSION = "analytics-v1"

_client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))

# ── Live schema introspection ─────────────────────────────────────────────────
#
# Queried once per process lifetime from information_schema.columns.
# Refreshes automatically on process restart (i.e. after migrations).
# Tables excluded from the SQL prompt because they are not analytics targets:
#   - agent_runs  (internal telemetry)
#   - past_jds    (RAG vector store, not HR analytics data)

_EXCLUDED_TABLES = frozenset({"agent_runs", "past_jds"})

_schema_cache: str | None = None


async def _fetch_live_schema(db: AsyncSession) -> str:
    """
    Introspect the live database and return a schema string for the SQL prompt.
    Uses MCP db_query when available; falls back to direct SQLAlchemy.
    Result is cached in _schema_cache for the lifetime of the process.
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    schema_sql = """
        SELECT
            c.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            tc.constraint_type,
            ccu.table_name  AS fk_table,
            ccu.column_name AS fk_column
        FROM information_schema.columns c
        LEFT JOIN information_schema.key_column_usage kcu
               ON kcu.table_schema = c.table_schema
              AND kcu.table_name   = c.table_name
              AND kcu.column_name  = c.column_name
        LEFT JOIN information_schema.table_constraints tc
               ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema    = c.table_schema
        LEFT JOIN information_schema.referential_constraints rc
               ON rc.constraint_name = kcu.constraint_name
        LEFT JOIN information_schema.key_column_usage ccu
               ON ccu.constraint_name = rc.unique_constraint_name
        WHERE c.table_schema = 'public'
          AND c.table_name   NOT IN ({excluded_list})
        ORDER BY c.table_name, c.ordinal_position
    """.format(excluded_list=", ".join(f"'{t}'" for t in _EXCLUDED_TABLES))

    client = mcp_client.get()
    if client is not None:
        raw_rows = await mcp_client.query(schema_sql)
    else:
        result = await db.execute(text(schema_sql))
        raw_rows = [dict(zip(result.keys(), r)) for r in result.fetchall()]

    # Group columns by table
    tables: dict[str, list[str]] = {}
    for row in raw_rows:
        r = row if isinstance(row, dict) else dict(row._mapping)
        table = r["table_name"]
        col_type = (r["data_type"] or "").upper()
        nullable = "" if r["is_nullable"] == "YES" else " NOT NULL"
        constraint = ""
        if r["constraint_type"] == "PRIMARY KEY":
            constraint = " PRIMARY KEY"
        elif r["constraint_type"] == "FOREIGN KEY" and r.get("fk_table"):
            constraint = f" REFERENCES {r['fk_table']}({r['fk_column']})"
        tables.setdefault(table, []).append(
            f"  {r['column_name']} {col_type}{nullable}{constraint}"
        )

    lines = ["PostgreSQL schema for the Invictus Hiring platform:\n"]
    for table, columns in tables.items():
        lines.append(f"TABLE {table} (")
        lines.extend(columns)
        lines.append(")\n")

    _schema_cache = "\n".join(lines)
    logger.info(f"Analytics: live schema loaded ({len(tables)} tables)")
    return _schema_cache


# ── NLP→SQL agent ──────────────────────────────────────────────────────────────

_SQL_SYSTEM_TEMPLATE = """You are a PostgreSQL expert for an HR hiring platform.
Generate a safe, read-only SELECT query to answer the user's question.

{schema}

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
    """Return a context hint for the SQL prompt when a session is active.
    Uses MCP db_get_session when available; falls back to direct SQLAlchemy."""
    if not session_id:
        return ""
    try:
        client = mcp_client.get()
        if client is not None:
            data = await mcp_client.get_session_context(session_id)
            req_id = data.get("id") or data.get("session_id")
            title = data.get("title")
        else:
            result = await db.execute(
                select(JDRequest).where(JDRequest.session_id == uuid.UUID(session_id))
            )
            req = result.scalar_one_or_none()
            req_id = str(req.id) if req else None
            title = req.title if req else None

        if req_id and title:
            return (
                f"\n\nACTIVE SESSION CONTEXT:\n"
                f"The user is currently viewing the JD session with:\n"
                f"  session_id = '{session_id}'\n"
                f"  jd_requests.id = '{req_id}'\n"
                f"  title = '{title}'\n"
                f"When the user says 'this job', 'this role', or 'this position', "
                f"filter by request_id = '{req_id}' (UUID literal, no quotes needed in SQL cast)."
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
        schema = await _fetch_live_schema(db)
        sql_system = _SQL_SYSTEM_TEMPLATE.format(schema=schema)
        session_context = await _resolve_session_context(session_id, db)

        # Step 1: generate SQL
        # System message is kept static (schema + rules) so OpenAI's prompt
        # caching can reuse the KV prefix across requests. Session context is
        # injected as a separate user-role message so the cacheable prefix never
        # changes between queries.
        sql_messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": sql_system},
        ]
        if session_context:
            sql_messages.append({"role": "user", "content": session_context})
            sql_messages.append({"role": "assistant", "content": "Understood. I will use that session context when writing the SQL."})
        sql_messages.append({"role": "user", "content": question})

        sql_resp = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=sql_messages,
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

        # Step 3: execute via MCP when available, fall back to SQLAlchemy
        try:
            client = mcp_client.get()
            if client is not None:
                data = await mcp_client.query(safe_sql)
                if data and "error" in data[0]:
                    raise RuntimeError(data[0]["error"])
            else:
                result = await db.execute(text(safe_sql))
                columns = list(result.keys())
                data = [dict(zip(columns, row)) for row in result.fetchmany(50)]
            rows_returned = len(data)
            logger.info(f"Analytics query returned {rows_returned} rows via {'MCP' if client else 'SQLAlchemy'} | sql={safe_sql[:120]}")
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
