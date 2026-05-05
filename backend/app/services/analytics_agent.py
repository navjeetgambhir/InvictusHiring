"""Supervisor + NLP-to-SQL analytics agent for HR/HM queries."""
import json
from typing import AsyncIterator

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)

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
"""

_FORMAT_SYSTEM = """You are a concise HR analytics assistant.
Given the user's question, the SQL used, and the query results, give a clear natural language answer.
- Use specific numbers and names from the results.
- Format lists as bullet points when there are multiple items.
- If the result set is empty, say so clearly and suggest why it might be.
- Keep answers under 200 words unless the data genuinely requires more detail.
"""


def _is_safe_sql(sql: str) -> bool:
    upper = sql.strip().upper()
    if not upper.startswith("SELECT"):
        return False
    blocked = {"INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE"}
    return not any(kw in upper.split() for kw in blocked)


async def stream_analytics_response(question: str, db: AsyncSession) -> AsyncIterator[str]:
    """Classify → generate SQL → execute → stream NL answer as NDJSON."""
    # Step 1: generate SQL
    sql_resp = await _client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SQL_SYSTEM},
            {"role": "user", "content": question},
        ],
        temperature=0,
    )
    raw_sql = (sql_resp.choices[0].message.content or "").strip()
    sql = raw_sql.replace("```sql", "").replace("```", "").strip()

    yield json.dumps({"type": "sql", "sql": sql}) + "\n"

    if not _is_safe_sql(sql):
        yield json.dumps({"type": "error", "message": "Only SELECT queries are permitted."}) + "\n"
        return

    # Step 2: execute
    try:
        result = await db.execute(text(sql))
        columns = list(result.keys())
        rows = result.fetchmany(50)
        data = [dict(zip(columns, row)) for row in rows]
        logger.info(f"Analytics query returned {len(data)} rows | sql={sql[:120]}")
    except Exception as exc:
        logger.error(f"Analytics SQL error: {exc} | sql={sql}")
        yield json.dumps({"type": "error", "message": f"Query failed: {exc}"}) + "\n"
        return

    # Step 3: stream NL answer
    prompt = (
        f"Question: {question}\n\n"
        f"SQL:\n{sql}\n\n"
        f"Results ({len(data)} rows):\n"
        f"{json.dumps(data[:20], indent=2, default=str)}"
    )
    stream = await _client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _FORMAT_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        stream=True,
        temperature=0.3,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield json.dumps({"type": "chunk", "text": delta}) + "\n"

    yield json.dumps({"type": "done"}) + "\n"
