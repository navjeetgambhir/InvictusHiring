# Backend & Agents Architecture Guide
# Invictus Hiring — Backend

This document describes the backend conventions, agent patterns, and implementation rules for the Invictus Hiring platform. Intended as a reference for adding new routes, agents, or services.

---

## 1. Project Structure

```
backend/
├── app/
│   ├── main.py                  ← FastAPI app, lifespan, CORS, router mounting, demo seeding
│   ├── core/
│   │   ├── config.py            ← pydantic_settings Settings (env vars)
│   │   ├── database.py          ← SQLAlchemy async engine + AsyncSessionLocal
│   │   ├── security.py          ← JWT encode/decode, bcrypt, Fernet PII
│   │   ├── dependencies.py      ← get_current_user, require_role(), CurrentUser
│   │   └── redis.py             ← conversation cache (push_message, get_history)
│   ├── db/
│   │   └── models.py            ← all 8 SQLAlchemy ORM models
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py          ← /api/auth (login, me, active-session)
│   │       ├── jd.py            ← /api/jd (draft, chat, approve, revert)
│   │       ├── jobs.py          ← /api/jobs (post/publish, job posting management)
│   │       ├── candidates.py    ← /api/candidates (job board, apply, applications)
│   │       ├── analytics.py     ← /api/analytics (route → supervisor dispatch)
│   │       ├── agent_cards.py   ← /.well-known/* (A2A agent card endpoints)
│   │       ├── ml.py            ← /api/ml (predict endpoint)
│   │       └── telemetry.py     ← /api/telemetry (quality report)
│   └── services/
│       ├── supervisor.py        ← intent classification (8 intents)
│       ├── jd_agent.py          ← JD drafter + RAG + stream revision
│       ├── job_poster_agent.py  ← platform publishing (LinkedIn/Indeed/Google Jobs)
│       ├── cv_screener.py       ← background CV scoring (0–100)
│       ├── analytics_agent.py   ← NLP→SQL with AST validation
│       ├── interview_agent.py   ← invitation generation + ICS
│       ├── ml_agent.py          ← fit/join model prediction + SHAP
│       ├── ml_predictor.py      ← sklearn pipeline, SHAP TreeExplainer
│       ├── ml_features.py       ← feature extraction for ML models
│       ├── rag.py               ← pgvector embed + retrieve
│       ├── email_sender.py      ← SMTP (fail-silent when unconfigured)
│       ├── agent_telemetry.py   ← fire_run() background telemetry
│       ├── sql_ast_validator.py ← sqlglot AST safety checks
│       └── guardrails/          ← output sanitisation helpers
├── migrations/                  ← numbered SQL migration files (manual apply)
├── tests/
│   ├── conftest.py              ← mock settings, override DB dependency
│   └── test_*.py
├── hiring_mcp/
│   └── server.py                ← FastMCP stdio server for Claude Desktop
├── ml_models/                   ← fit_model.joblib, join_model.joblib
└── ml_train.py                  ← training script (GradientBoosting)
```

---

## 2. Core Patterns

### Settings (`app/core/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    DATABASE_URL: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET_KEY: str = ""
    JWT_EXPIRE_MINUTES: int = 480
    ENCRYPTION_KEY: str = ""     # Fernet key for PII
    SMTP_HOST: str = ""          # empty → email disabled
    ...

settings = Settings()
```

Always import from `app.core.config import settings`. Never read `os.environ` directly.

### Async Database Sessions

Two patterns — use the right one:

**Pattern A — Route handler (request-scoped):**
```python
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

@router.get("/foo")
async def my_route(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MyModel))
    ...
```
`get_db` yields a session and calls `db.close()` after the response is sent. Safe for regular routes.

**Pattern B — Inside StreamingResponse generators or background tasks:**
```python
from app.core.database import AsyncSessionLocal

async def my_generator():
    # request-scoped `db` is already closed here
    async with AsyncSessionLocal() as write_db:
        obj = await write_db.get(MyModel, pk)
        obj.status = "done"
        await write_db.commit()
    yield b"data\n"
```
Use `AsyncSessionLocal()` whenever the commit happens outside the request lifecycle. This is the pattern used in `jobs.py` for publishing and in `agent_telemetry.py` for fire-and-forget writes.

### ORM Models (`app/db/models.py`)

SQLAlchemy 2.0 style with typed `Mapped` columns:

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
import uuid

class Base(DeclarativeBase):
    pass

class MyModel(Base):
    __tablename__ = "my_table"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

All PKs are UUIDs as strings. All timestamps are timezone-aware UTC. Optional fields use `Mapped[T | None]`.

---

## 3. Auth & Security (`app/core/security.py`, `app/core/dependencies.py`)

### JWT flow

```python
# Encode (login)
token = create_access_token({"sub": user.id, "role": user.role})

# Decode (middleware)
payload = decode_token(token)  # raises HTTPException 401 on invalid/expired
```

Tokens carry `sub` (user UUID) and `role` (`hr` | `hm`). Expiry defaults to 480 minutes.

### Route protection

```python
from app.core.dependencies import get_current_user, require_role, CurrentUser

# Any authenticated user:
@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "role": user.role}

# Role-restricted:
@router.post("/approve")
async def approve(
    user: CurrentUser = Depends(require_role("hr")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

`CurrentUser` is a plain dataclass: `id: str`, `role: str`, `email: str`.

### PII encryption

Emails are never stored in plaintext:
```python
from app.core.security import encrypt_email, hash_email, decrypt_email

# Store:
user.email_encrypted = encrypt_email(raw_email)   # Fernet
user.email_hash = hash_email(raw_email)           # SHA-256 blind index

# Lookup:
stmt = select(User).where(User.email_hash == hash_email(raw_email))

# Read:
plain = decrypt_email(user.email_encrypted)
```

---

## 4. Agent Architecture

### Supervisor (`app/services/supervisor.py`)

Every message from the frontend goes to `/api/analytics/route`, which calls the supervisor:

```python
@dataclass
class RoutingDecision:
    intent: str          # one of 8 values
    confidence: float
    reasoning: str

# 8 intents:
# jd_draft | jd_chat | jd_revise | approve | publish | analytics | ml_predict | other
```

The supervisor receives: `message`, `pipeline_state`, `session_id`, `job_title`, `job_department`, and the last 6 messages of conversation history. It uses `gpt-4o-mini` with a JSON-mode system prompt. Falls back to `other` on error or confidence < 0.5.

### Agent pattern (all 6 agents)

Every agent follows this structure:

```python
AGENT_PROMPT_VERSION = "agent-v1"   # increment when prompt changes

async def run_agent(inputs, db: AsyncSession) -> AsyncGenerator[str, None]:
    # 1. Build messages list
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    # 2. Call OpenAI (streaming or function calling)
    client = wrap_openai(openai.AsyncOpenAI())   # LangSmith tracing
    stream = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        stream=True,
    )

    # 3. Stream chunks to caller
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        yield delta

    # 4. Fire telemetry (never awaited inline)
    asyncio.create_task(fire_run(
        agent_name="my_agent",
        operation="run",
        prompt_version=AGENT_PROMPT_VERSION,
        ...
    ))
```

### Streaming response pattern

Routes that stream use `StreamingResponse` with `media_type="text/plain"` (chat) or `"application/x-ndjson"` (ML, job poster):

```python
from fastapi.responses import StreamingResponse

@router.post("/stream")
async def stream_endpoint(req: MyRequest, db: AsyncSession = Depends(get_db)):
    async def generate():
        async for chunk in my_agent(req, db):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain")
```

**Critical:** Any DB `commit()` needed after streaming must use `AsyncSessionLocal()` inside the generator — the request-scoped `db` is closed before the generator resumes.

### NDJSON streaming (ML agent, job poster)

```python
# Server sends newline-delimited JSON events:
yield json.dumps({"type": "result", "data": {...}}) + "\n"
yield json.dumps({"type": "chunk", "text": "..."}) + "\n"
yield json.dumps({"type": "done"}) + "\n"

# Frontend reads with a streaming fetch + line split
```

The `type` field drives frontend rendering: `result` events carry structured data (ML scores, SHAP), `chunk` events carry text tokens, `done` signals completion.

---

## 5. Agent Telemetry (`app/services/agent_telemetry.py`)

Every OpenAI call writes one `AgentRun` record. Always fire-and-forget:

```python
import asyncio
from app.services.agent_telemetry import fire_run

# Inside any agent, after the OpenAI call completes:
asyncio.create_task(fire_run(
    agent_name="jd_agent",
    operation="draft",
    prompt_version=JD_PROMPT_VERSION,
    model=settings.OPENAI_MODEL,
    status="success",              # or "error"
    latency_ms=elapsed_ms,
    input_tokens=usage.prompt_tokens,
    output_tokens=usage.completion_tokens,
    metrics={"draft_version": 2},  # agent-specific JSON
))
```

`fire_run` opens its own `AsyncSessionLocal()` session — never shares the request-scoped `db`. The call must never be `await`ed inline or it will block the streaming response.

### Quality metrics by agent

| Agent | `metrics` keys |
|-------|----------------|
| supervisor | `intent`, `confidence` |
| jd_agent | `draft_version` |
| analytics | `sql_passed_validation`, `sql_blocked_reason`, `rows_returned`, `has_session_context` |
| cv_screener | `score`, `recommendation` |
| ml_agent | `prediction_type`, `candidate_count`, `shap_explanations` |

---

## 6. RAG Pipeline (`app/services/rag.py`)

```python
async def embed(text: str) -> list[float]:
    client = wrap_openai(openai.AsyncOpenAI())
    resp = await client.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding

async def retrieve_similar_jds(query: str, db: AsyncSession, top_k: int = 5) -> list[PastJD]:
    vec = await embed(query)
    rows = await db.execute(
        select(PastJD)
        .order_by(PastJD.embedding.op("<=>")(vec))   # pgvector cosine distance
        .limit(top_k)
    )
    return rows.scalars().all()
```

- Model: `text-embedding-3-small` (1 536 dimensions)
- Similarity threshold: `RAG_SIMILARITY_THRESHOLD = 0.75` (configurable)
- Each retrieved JD is truncated to 1 200 chars before being added to the prompt
- Retrieval scores are logged at DEBUG level with job title

---

## 7. Analytics Agent (`app/services/analytics_agent.py`)

### SQL safety — two layers

**Layer 1 — Regex:** strips trailing semicolons, checks for stacked queries.

**Layer 2 — AST validator (`sql_ast_validator.py`):**
```python
from app.services.sql_ast_validator import validate_sql

ok, reason = validate_sql(generated_sql)
if not ok:
    return f"I can't run that query: {reason}"
```

`validate_sql` uses `sqlglot` to parse and walk the AST. Blocks:
- Non-`SELECT` statements (INSERT, UPDATE, DELETE, DROP, …)
- Dangerous functions (`pg_read_file`, `dblink`, `lo_export`, …)
- Unknown tables (only `jd_requests`, `jd_drafts`, `candidate_applications`, `job_postings`, `chat_messages` are allowed)
- Stacked queries (multiple statements)

### Output sanitisation

```python
# Strip UUIDs/emails from narrated answer:
safe_answer = _sanitise_output(raw_answer)

# Redact UUIDs/emails from SQL shown in UI (execution SQL is never changed):
safe_sql = _sanitise_sql_for_display(generated_sql)
```

### Session context injection

```python
async def _resolve_session_context(session_id: str, db: AsyncSession):
    req = await db.execute(select(JDRequest).where(JDRequest.session_id == session_id))
    if req:
        return {"request_id": req.id, "title": req.title}
    return {}
```

The resolved `request_id` and `title` are injected into the SQL generation prompt so "how many candidates applied for this job?" produces `WHERE jd_requests.id = '<uuid>'`.

---

## 8. Redis Caching (`app/core/redis.py`)

Two namespaces, both fail silently:

```python
HISTORY_KEY = "conversation:{session_id}"   # list, 24h TTL
ACTIVE_SESSION_KEY = "active_session:{user_id}"  # string, 30-day TTL

async def push_message(session_id: str, role: str, content: str) -> None:
    try:
        r = await get_redis()
        await r.rpush(HISTORY_KEY.format(session_id=session_id), json.dumps({"role": role, "content": content}))
        await r.expire(HISTORY_KEY.format(session_id=session_id), 86400)
    except Exception:
        logger.warning("Redis push failed — continuing without cache")

async def get_history(session_id: str) -> list[dict]:
    try:
        r = await get_redis()
        raw = await r.lrange(HISTORY_KEY.format(session_id=session_id), 0, -1)
        return [json.loads(m) for m in raw]
    except Exception:
        logger.warning("Redis get failed — falling back to Postgres")
        return []   # caller falls back to DB
```

Redis is **optional** — the app works without it. On cache miss, callers fall back to querying `chat_messages` in Postgres.

---

## 9. ML Pipeline (`app/services/ml_predictor.py`)

Two lazy-loaded sklearn models:

```python
_fit_model: dict | None = None    # {"pipeline": Pipeline, "features": [...]}
_join_model: dict | None = None

def _load_fit_model() -> dict:
    global _fit_model
    if _fit_model is None:
        _fit_model = joblib.load("ml_models/fit_model.joblib")
    return _fit_model
```

Models are stored as dicts (not bare pipelines) because `feature_names_in_` is read-only on `Pipeline`.

### SHAP explanations

```python
def explain_fit(application: CandidateApplication) -> list[dict]:
    bundle = _load_fit_model()
    pipeline: Pipeline = bundle["pipeline"]
    features = bundle["features"]

    X = _build_feature_row(application, features)
    X_scaled = pipeline.named_steps["scaler"].transform(X)
    explainer = shap.TreeExplainer(pipeline.named_steps["clf"])
    shap_values = explainer.shap_values(X_scaled)

    return sorted([
        {"feature": f, "label": _FIT_LABELS[f], "contribution": float(v),
         "direction": "up" if v > 0 else "down", "raw_value": float(X[0][i])}
        for i, (f, v) in enumerate(zip(features, shap_values[0]))
    ], key=lambda x: abs(x["contribution"]), reverse=True)[:5]
```

SHAP runs on the pre-scaled input (not raw features). Top 5 by absolute contribution are returned. Results are sent in the `results` NDJSON event and rendered as collapsible factor bars in `ChatMessage.tsx`.

---

## 10. Testing (`backend/tests/conftest.py`)

### Mock settings

```python
import pytest
from unittest.mock import patch, AsyncMock

@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.core.config.settings.DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr("app.core.config.settings.REDIS_URL", "")
```

### Override DB dependency

```python
@pytest.fixture
def mock_db():
    return AsyncMock()

@pytest.fixture
def test_client(mock_db):
    from app.main import app
    from app.core.database import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

**Rules:**
- No real DB connections in tests — always mock `get_db`
- No real OpenAI calls — mock `openai.AsyncOpenAI` or the service function directly
- No real Redis — leave `REDIS_URL` empty (fail-silent path runs automatically)
- Telemetry `fire_run` calls should be mocked to avoid background task errors in tests

---

## 11. Database Models Reference

| Model | Table | Key fields |
|-------|-------|-----------|
| `User` | `users` | `email_hash`, `email_encrypted`, `password_hash`, `role` |
| `JDRequest` | `jd_requests` | `session_id`, `title`, `dept`, `location`, `salary_band`, `status`, `published_at`, `expires_at`, `max_applications` |
| `JDDraft` | `jd_drafts` | `request_id`, `version` (increments), `content`, `rejection_feedback`, `prompt_version` |
| `ChatMessage` | `chat_messages` | `request_id`, `role` (`user`\|`assistant`), `content` |
| `PastJD` | `past_jds` | `title`, `dept`, `content`, `embedding` (`vector(1536)`) |
| `JobPosting` | `job_postings` | `request_id`, `platform`, `formatted_content`, `post_url`, `status` |
| `CandidateApplication` | `candidate_applications` | `screening_score`, `screening_recommendation`, `shortlisted`, `interview_status`, `interview_scheduled_at`, `outcome`, `offer_accepted` |
| `InterviewInvitation` | `interview_invitations` | `application_id`, `email_subject`, `email_body`, `interview_questions` (JSON), `email_sent_at` |
| `AgentRun` | `agent_runs` | `agent_name`, `operation`, `prompt_version`, `model`, `status`, `latency_ms`, `input_tokens`, `output_tokens`, `metrics` (JSON) |

---

## 12. Adding a New Agent — Rules

1. **Prompt version constant** — add `MY_AGENT_PROMPT_VERSION = "my-agent-v1"` at the top of the service file. Increment the version string every time the system prompt changes.

2. **Wrap the OpenAI client** — always `wrap_openai(openai.AsyncOpenAI())` for LangSmith tracing. Never use a bare `openai.AsyncOpenAI()`.

3. **Fire telemetry async** — call `asyncio.create_task(fire_run(...))` at the end of every OpenAI call. Never `await` it inline.

4. **Streaming generators don't own the request DB session** — if the generator needs a DB write, open `async with AsyncSessionLocal() as write_db:` inside the generator.

5. **NDJSON for structured output** — if the agent emits both structured data and text, use newline-delimited JSON with a `type` field (`result`, `chunk`, `done`). Plain text streaming is for chat-only agents.

6. **Supervisor must know about the new intent** — add the intent name to `VALID_INTENTS` in `supervisor.py` and update the `_ROUTE_SYSTEM` prompt. Add a handler branch in `analytics.py` route.

7. **Fail gracefully on missing credentials** — external integrations (SMTP, LinkedIn, etc.) must check config and return `False`/empty rather than raise when credentials are absent.

8. **No blocking IO** — all DB, HTTP, and file IO must use `await` or `asyncio.to_thread()` for sync libs. Never call sync blocking functions directly in an async route.

9. **Track prompt versions in telemetry** — include `prompt_version=MY_AGENT_PROMPT_VERSION` in every `fire_run()` call so quality trends are attributable to specific prompt changes.

10. **Add a migration file** — new DB columns go in a numbered file under `backend/migrations/`. Include the manual apply command in `CLAUDE.md`. Never use `Base.metadata.create_all()` in production code.

---

## 13. Adding a New Route — Rules

1. **Create a file in `app/api/routes/`** and mount it in `app/main.py`:
   ```python
   from app.api.routes import my_route
   app.include_router(my_route.router, prefix="/api/my-route", tags=["my-route"])
   ```

2. **Use `Depends(get_db)` for the DB session** — never create sessions manually in route handlers.

3. **Protect with `Depends(require_role("hr"))`** for HR-only endpoints; `Depends(get_current_user)` for any authenticated user; no dependency for public endpoints.

4. **Return typed Pydantic response models** — define `class MyResponse(BaseModel)` and use `response_model=MyResponse` on the decorator.

5. **Background tasks via `BackgroundTasks`** — for fire-and-forget work that doesn't need streaming (e.g. sending email after apply), use FastAPI's `BackgroundTasks`, not `asyncio.create_task()` directly (avoids task orphaning on shutdown).

6. **Paginate list endpoints** — accept `page: int = 1` and `page_size: int = 10` query params. Apply filters in SQL `WHERE` (not Python post-processing) so `OFFSET`/`LIMIT` operates on the correct set.