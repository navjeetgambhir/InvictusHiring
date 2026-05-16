# Backend Architecture — Invictus Hiring AI Platform

## 1. Overview

The backend is a **FastAPI async application** (Python 3.13) that exposes a REST + streaming API consumed by the React frontend. It orchestrates six AI agents, manages a PostgreSQL database via SQLAlchemy 2.0 async, and uses Redis for conversation caching.

```
frontend (React)
      │  HTTP / SSE
      ▼
FastAPI (uvicorn)
      │
      ├── Auth           (JWT HS256)
      ├── Supervisor     (gpt-4o-mini — intent routing)
      │      │
      │      ├── Agent 1: JD Drafter      (jd_agent.py)
      │      ├── Agent 2: Job Poster      (job_poster_agent.py)
      │      ├── Agent 3: CV Screener     (cv_screener.py)
      │      ├── Agent 4: Analytics       (analytics_agent.py)
      │      ├── Agent 5: Interview Sched (interview_agent.py)
      │      └── Agent 6: ML Predictor   (ml_agent.py + ml_predictor.py)
      │
      ├── PostgreSQL 16 + pgvector
      ├── Redis (chat history cache)
      └── OpenAI API (GPT-4o, GPT-4o-mini, text-embedding-3-small)
```

---

## 2. Directory Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI app, lifespan, CORS, router registration
│   ├── core/
│   │   ├── config.py              # Pydantic Settings (reads .env)
│   │   ├── database.py            # SQLAlchemy async engine, AsyncSessionLocal, Base, get_db
│   │   ├── dependencies.py        # get_current_user, require_role FastAPI deps
│   │   └── redis.py               # push_message, get_history, active session key
│   ├── db/
│   │   └── models.py              # All SQLAlchemy ORM models
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py            # /api/auth — register, login, me, active-session
│   │       ├── jd.py              # /api/jd — draft, chat, approve, revert, sessions
│   │       ├── jobs.py            # /api/jobs — post, postings, indeed feed, google jobs
│   │       ├── candidates.py      # /api/candidates — job board, apply, applications, outcome
│   │       ├── interviews.py      # /api/interviews — shortlist, generate, approve, schedule, ics
│   │       ├── analytics.py       # /api/analytics — route (supervisor), classify, query
│   │       ├── ml.py              # /api/ml — predict
│   │       └── telemetry.py       # /api/telemetry — quality report
│   └── services/
│       ├── supervisor.py          # agent1_route(), agent2_publish()
│       ├── jd_agent.py            # JD drafting + revision + chat
│       ├── job_poster_agent.py    # Platform-specific JD reformatting
│       ├── cv_screener.py         # PDF/DOCX extraction + GPT scoring
│       ├── analytics_agent.py     # NLP→SQL→execute→narrate
│       ├── interview_agent.py     # Invitation email + questions generation
│       ├── ml_agent.py            # NL query parser + prediction streamer
│       ├── ml_predictor.py        # Model loading, predict_fit/join, explain_fit/join (SHAP)
│       ├── ml_features.py         # Feature extraction from CandidateApplication + JDRequest
│       ├── rag.py                 # embed(), retrieve_similar_jds()
│       ├── sql_ast_validator.py   # sqlglot AST safety check
│       ├── agent_telemetry.py     # fire_run() — writes to agent_runs
│       ├── email_sender.py        # SMTP send helpers
│       └── platforms/
│           ├── linkedin.py
│           ├── indeed.py
│           └── google_jobs.py
├── migrations/                    # SQL migration files (applied manually)
├── ml_models/                     # fit_model.joblib, join_model.joblib
├── ml_train.py                    # Re-training script
├── hiring_mcp/server.py           # FastMCP stdio MCP server
└── tests/                         # pytest test suite (all mocked — no real DB/OpenAI)
```

---

## 3. Request Lifecycle

### Standard protected request
```
Client → Authorization: Bearer <JWT>
       → FastAPI route handler
       → get_current_user() dependency
           → decode JWT (HS256, JWT_SECRET_KEY)
           → lookup user by email_hash in DB
           → inject CurrentUser into handler
       → handler executes
       → SQLAlchemy async session (get_db) auto-committed or rolled back by FastAPI
```

### Chat message (most complex path)
```
POST /api/analytics/route
  body: { message, session_id, job_title, job_department, pipeline_state, history }

  1. supervisor.agent1_route()
       → inject last 6 messages + pipeline state
       → GPT-4o-mini → JSON routing decision
       → returns { intent, confidence, ... }

  2. Route dispatch (in analytics.py):
       jd_draft    → jd_agent.stream_initial_draft()   → StreamingResponse (plain text)
       jd_chat     → jd_agent.stream_chat_reply()      → StreamingResponse (plain text)
       jd_revise   → jd_agent.stream_revision()        → StreamingResponse (plain text)
       approve     → handled by /api/jd/approve
       publish     → handled by /api/jobs/post/{session_id}
       analytics   → analytics_agent.stream_answer()   → StreamingResponse (NDJSON)
       ml_predict  → ml_agent.stream_ml_predictions()  → StreamingResponse (NDJSON)
       other       → returns static JSON { type: "chunk", text: "..." }
```

---

## 4. Database Access Patterns

### Session management
- Every route handler receives `db: AsyncSession = Depends(get_db)` — a request-scoped async session.
- Background tasks that outlive the request (CV screening, ML prediction saves, past_jds writes, publish commits) open their own `async with AsyncSessionLocal() as db:` session to avoid using a closed request session.

### ORM usage
All queries use SQLAlchemy 2.0 style:
```python
result = await db.execute(select(Model).where(Model.field == value))
row = result.scalar_one_or_none()
```
Raw SQL is used only in the analytics agent (NLP-generated, validated by AST before execution) and schema introspection.

### Foreign key relationships
```
jd_requests  ──< jd_drafts           (request_id)
jd_requests  ──< chat_messages       (request_id)
jd_requests  ──< job_postings        (request_id)
jd_requests  ──< candidate_applications (request_id)
candidate_applications ──< interview_invitations (application_id)
candidate_applications ──< ml_predictions        (application_id, CASCADE DELETE)
```

---

## 5. Agent Details

### Agent 1 — JD Drafter (`jd_agent.py`)
- `stream_initial_draft(request, history, past_jds)` → yields plain text chunks, then `\n\n__SESSION_ID__<uuid>` sentinel
- `stream_chat_reply(request, history, message)` → same output format; promotes reply to new `JDDraft` version if it looks like a full JD
- `stream_revision(request, draft, feedback)` → always creates a new `JDDraft` version
- Prompt version: `jd-v1`

RAG injection: `retrieve_similar_jds()` returns up to 5 results above threshold 0.56. Each truncated to 1200 chars in the system prompt. Attribution footer yielded as final stream chunk.

### Agent 2 — Job Poster (`job_poster_agent.py` + `routes/jobs.py`)
- `agent2_publish(content, title, session_id)` → yields NDJSON lines
- Dispatches to `linkedin.py`, `indeed.py`, `google_jobs.py` — all fail gracefully without credentials
- DB writes (status=published, JobPosting rows) happen inside the generator using a fresh session
- After `done` event: `asyncio.create_task(_save_to_past_jds(...))` for RAG feedback loop

### Agent 3 — CV Screener (`cv_screener.py`)
- `screen_candidate(application_id)` — always invoked as `asyncio.create_task`
- Extracts text via `_extract_sync()` (pypdf / python-docx / plain text)
- GPT-4o returns structured JSON: score (0–100), summary, strengths, gaps, recommendation
- Writes to `CandidateApplication.screening_*` columns
- Prompt version: `screen-v1`

### Agent 4 — Analytics (`analytics_agent.py`)
- `stream_answer(question, db, session_id)` → yields NDJSON
- Schema cached process-lifetime in `_schema_cache` via `_fetch_live_schema()`
- Session context injected as user/assistant message pair (keeps system prompt cacheable)
- SQL validated by `sql_ast_validator.py` before execution
- Output sanitised by `_sanitise_output()` (UUID + email regex strip)
- Prompt version: `analytics-v1`

### Agent 5 — Interview Scheduler (`interview_agent.py`)
- `generate_invitation(application_id, db)` → GPT-4o returns `{email_subject, email_body, interview_questions}`
- `approve_and_send(invitation_id, edits, db)` → applies HR edits → SMTP send
- `generate_ics(application)` → produces RFC 5545 `.ics` calendar file

### Agent 6 — ML Predictor (`ml_agent.py` + `ml_predictor.py`)
- `stream_ml_predictions(question, db, session_id)` → yields NDJSON
- GPT-4o-mini parses intent: `prediction_type`, `session_id`, `candidate_name`, `shortlisted_only`, `sort_by`
- Runs `predict_fit(app, job)` / `predict_join(app, job)` on each matched candidate
- `explain_fit()` / `explain_join()` use `shap.TreeExplainer` on the GBT step
- Streams `results` event (structured data for UI cards) before narrative summary
- Persists to `ml_predictions` via `asyncio.create_task(_save_predictions(results, prediction_type))`
- Prompt version: `ml-agent-v1`

#### ML model loading (lazy, process-cached)
```python
# ml_predictor.py
_fit_bundle: dict | None = None

def _load_fit() -> dict:
    global _fit_bundle
    if _fit_bundle is None:
        _fit_bundle = joblib.load("ml_models/fit_model.joblib")
    return _fit_bundle
```

---

## 6. Streaming Protocols

### Plain text (JD drafts)
```
<text chunks>...\n\n__SESSION_ID__<uuid>
```
Frontend `readDraftStream()` buffers the last 50 chars to avoid rendering the sentinel.

### NDJSON (analytics, ML, job posting)
Each line is a complete JSON object terminated with `\n`:

**Analytics:**
```jsonl
{"type": "sql",    "sql": "SELECT ..."}
{"type": "chunk",  "text": "There are 3 ..."}
{"type": "done"}
```

**ML:**
```jsonl
{"type": "results", "data": [{application_id, candidate_name, fit_probability, join_probability, fit_explanation, join_explanation, ...}]}
{"type": "chunk",   "text": "Alice scores highest..."}
{"type": "done"}
```

**Job posting:**
```jsonl
{"type": "start",  "platform": "linkedin"}
{"type": "posted", "platform_id": "linkedin", "url": "...", "content": "..."}
{"type": "done"}
```

---

## 7. Security

### Authentication
- `POST /auth/login` → bcrypt verify → HS256 JWT (exp = JWT_EXPIRE_MINUTES)
- Every protected route: `Authorization: Bearer <token>` → `get_current_user()` → `CurrentUser`
- JWT payload: `sub=email_hash`, `role=hr|hm`, `exp`

### PII
| Data | Storage |
|------|---------|
| Email | SHA-256 blind index + Fernet ciphertext (separate columns) |
| Password | bcrypt one-way hash |
| CV files | Disk at `cv_uploads/`; served only to authenticated HR |
| Candidate names/emails in analytics | Stripped from narrated output by `_sanitise_output()` |

### SQL injection
Analytics agent: NLP-generated SQL passes through two independent layers before execution:
1. Regex pre-check (stacked queries, dangerous keywords)
2. sqlglot AST walk (SELECT-only, allowlisted tables, forbidden functions)

---

## 8. Background Task Pattern

All slow / non-critical work runs as fire-and-forget:

```python
asyncio.create_task(some_async_fn(...))  # never awaited inline
```

Tasks that outlive the request use a fresh `AsyncSessionLocal()` session, not the request-scoped `db` (which may be closed by the time the task runs).

| Task | Trigger | Function |
|------|---------|----------|
| CV screening | POST /apply | `screen_candidate(app_id)` |
| Agent telemetry | Every agent call | `fire_run(...)` |
| Save to past_jds | Job published | `_save_to_past_jds(title, dept, content)` |
| Save ML predictions | After ML query | `_save_predictions(results, prediction_type)` |

---

## 9. Redis Caching

```
Key:   conversation:{session_id}    → Redis List, 24-hour TTL
Key:   active_session:{user_id}     → String (session_id UUID), 30-day TTL
```

Chat history lookup:
1. `get_history(session_id)` → Redis LRANGE (O(N) on list length)
2. Cache miss → query `chat_messages` ordered by `created_at` → `seed_history()` warms Redis
3. Both `push_message` and `get_history` fail silently (log warning) — Redis is optional

---

## 10. Telemetry

`agent_telemetry.fire_run()` writes to `agent_runs` after every OpenAI call:

| Agent | agent_name | operation | Extra metrics |
|-------|-----------|-----------|---------------|
| Supervisor | `supervisor` | `route` | intent, confidence |
| JD Drafter | `jd_drafter` | `initial_draft \| revision \| chat` | draft_version |
| CV Screener | `cv_screener` | `screen` | screening_score, recommendation |
| Analytics | `analytics` | `query` | sql_passed_validation, rows_returned, has_session_context |
| Interview | `interview_scheduler` | `generate \| send` | — |
| ML Predictor | `ml_predictor` | `predict` | prediction_type, candidate_count, shap_explanations |

`GET /api/telemetry/quality?days=30` aggregates all tables into a quality dashboard.

---

## 11. ML Prediction Pipeline

```
NL question
    │
    ▼ GPT-4o-mini (_parse_query)
    │  → {prediction_type, session_id, candidate_name, shortlisted_only, sort_by}
    │
    ▼ _fetch_applications(db, ...)
    │  → [(CandidateApplication, JDRequest), ...]
    │
    ▼ ml_features.py — extract_fit_features(app, job) / extract_join_features(app, job)
    │  → numpy array matching model's expected feature order
    │
    ▼ ml_predictor.py
    │  predict_fit(app, job)  → int 0–100  (GBT predict_proba * 100)
    │  predict_join(app, job) → int 0–100
    │  explain_fit(app, job)  → top-5 SHAP factors
    │  explain_join(app, job) → top-5 SHAP factors
    │
    ▼ Sort + stream results NDJSON
    │
    ▼ GPT-4o narrative summary (streaming)
    │
    ▼ asyncio.create_task(_save_predictions(...))
         → INSERT INTO ml_predictions (one row per candidate)
```

### Feature sets
**Fit model features** (from `extract_fit_features`): screening score, skill overlap, years experience, seniority match, has cover letter, department match, etc.

**Join model features** (from `extract_join_features`): interview format, offer amount (normalised), days to respond, interview rounds, shortlisted flag, etc.

### SHAP explanation format
```python
[
  {
    "feature":      "screening_score",
    "label":        "Screening Score",
    "contribution": 0.412,
    "direction":    "positive",   # or "negative"
    "raw_value":    78,
  },
  ...
]
```

---

## 12. RAG Pipeline

```
User submits JD requirements
    │
    ▼ embed(title + department + required_skills)
    │  → OpenAI text-embedding-3-small → float[1536]
    │
    ▼ pgvector cosine search
    │  SELECT ... FROM past_jds ORDER BY embedding <=> :query_vec
    │  WHERE 1 - (embedding <=> :query_vec) >= RAG_SIMILARITY_THRESHOLD (0.56)
    │  LIMIT RAG_TOP_K (5)
    │
    ▼ Each result truncated to 1200 chars
    │
    ▼ Injected into JD Drafter system prompt as reference examples
    │
    ▼ Attribution footer yielded at end of stream (if hits exist)
         → "*Drafted with reference to archived JDs: [Title — Dept]*"
```

**past_jds population:**
- Initial seed: `Data/seed_past_jds.py` (scraped real job data, batched embedding API calls)
- Feedback loop: every published JD → `_save_to_past_jds()` background task

---

## 13. Migrations

Applied manually via `docker exec`:
```bash
docker exec hiring_postgres psql -U hiring_user -d hiring_db \
  -f /docker-entrypoint-initdb.d/<migration>.sql
```

| File | Contents |
|------|---------|
| `001_init.sql` | Core schema (auto-runs via Docker entrypoint) |
| `002_candidate_cv_screening.sql` | CV + screening columns |
| `003_interview_scheduling.sql` | Interview scheduling columns |
| `004_agent_runs.sql` | `agent_runs` table |
| `005_ml_outcome_fields.sql` | `outcome`, offer, `interview_rounds`, `days_to_respond` |
| `006_cover_letter_file.sql` | `cover_letter_filename` column |
| `007_job_expiry.sql` | `expires_at`, `max_applications`, `published_at` |
| `008_prompt_versions.sql` | `prompt_version` on drafts + applications |
| `009_ml_predictions.sql` | `ml_predictions` table + indexes |

---

## 14. MCP Server (`hiring_mcp/server.py`)

FastMCP stdio server exposing DB query tools and platform posting tools to Claude Desktop or external agents. Run with:

```bash
PYTHONPATH=backend python backend/hiring_mcp/server.py
```

Exposed tools: `db_list_sessions`, `db_get_session`, `db_get_postings`, `db_search_similar_jds`, `linkedin_post_job`, `indeed_post_job`, `google_jobs_post_job`.