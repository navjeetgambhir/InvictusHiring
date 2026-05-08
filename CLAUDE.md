# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Hard Rules

- **Never read `backend/.env` or `backend/app/core/config.py`** — these files contain secrets. If config values are needed, ask the user directly.

# Invictus Hiring — Capstone Project

AI-powered hiring automation platform with human-in-the-loop for JD drafting, candidate shortlisting, and interview coordination.

## Running the App

```bash
# 1. Start all services (Postgres + pgvector, Redis, Mailhog)
docker compose up -d

# 2. Start the backend (auto-reloads on file changes)
cd /Users/navjeetkaur/Desktop/Capstone
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000

# 3. Start the frontend
cd frontend && npm run dev -- --port 3000
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API docs | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |
| Mailhog (email preview) | http://localhost:8025 |

## Running Tests

```bash
# All tests (no real DB or OpenAI calls — all mocked)
cd /Users/navjeetkaur/Desktop/Capstone
PYTHONPATH=backend .venv/bin/pytest -v

# Single test file
PYTHONPATH=backend .venv/bin/pytest backend/tests/test_sql_ast_validator.py -v

# Single test by name
PYTHONPATH=backend .venv/bin/pytest -v -k "test_name_here"
```

## RAG Evaluation (RAGAS)

`backend/eval_rag.py` evaluates the pgvector retrieval pipeline across 4 RAGAS metrics:
Faithfulness, Answer Relevancy, Context Precision, Context Recall.

```bash
# Offline — uses hardcoded golden dataset, no DB required (costs ~$0.01 OpenAI)
OPENAI_API_KEY=sk-... PYTHONPATH=backend python backend/eval_rag.py

# Live — real DB retrieval + JD agent generation
OPENAI_API_KEY=sk-... PYTHONPATH=backend python backend/eval_rag.py --live
```

Saves results to `eval_rag_results.json`. Exits non-zero if any metric falls below threshold
(0.70 for faithfulness/relevancy, 0.60 for precision/recall) — CI-safe.

## Demo Accounts (auto-seeded on startup)

| Email | Role | Password |
|-------|------|----------|
| `hr@invictushiring.co` | HR (Sarah Chen) | `password` |
| `hm@invictushiring.co` | Hiring Manager (Alex Kumar) | `password` |

## Environment Variables (`backend/.env`)

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

DATABASE_URL=postgresql+asyncpg://hiring_user:hiring_pass@localhost:5432/hiring_db?ssl=disable
REDIS_URL=redis://localhost:6379/0
RAG_TOP_K=5
RAG_SIMILARITY_THRESHOLD=0.75

# Auth
ENCRYPTION_KEY=<fernet-key>   # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
JWT_SECRET_KEY=<random-string>
JWT_EXPIRE_MINUTES=480

# SMTP (optional — app works without; local dev: point at Mailhog)
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@invictushiring.co
SMTP_USE_TLS=false

# Job board integrations (all optional — app works without them)
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_AUTHOR_URN=           # e.g. urn:li:person:ABC123 or urn:li:organization:12345
INDEED_PUBLISHER_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=   # full JSON of GCP service account key file (as string)
APP_BASE_URL=http://localhost:8000
```

## Architecture

### Agent Pipeline

Six AI agents, all using OpenAI streaming or function calling, orchestrated by a supervisor:

```
User message
    │
    ▼
Supervisor (gpt-4o-mini) — classifies into 8 intents:
  jd_draft | jd_chat | jd_revise | approve | publish | analytics | ml_predict | other
    │
    ├─▶ Agent 1: JD Drafter (jd_agent.py)
    │     extract_requirements → RAG (pgvector) → stream JD draft
    │     revise on rejection feedback, increments draft version
    │
    ├─▶ Agent 2: Job Poster (job_poster_agent.py)
    │     reformat JD per platform → publish LinkedIn/Indeed/Google Jobs
    │     streams NDJSON progress events
    │
    ├─▶ Agent 3: CV Screener (cv_screener.py)
    │     runs in background after candidate applies
    │     extracts PDF/DOCX text → scores 0–100 + recommendation
    │
    ├─▶ Agent 4: Analytics (analytics_agent.py)
    │     NLP → SQL via OpenAI → AST-validated → executed against Postgres
    │
    ├─▶ Agent 5: Interview Scheduler (interview_agent.py)
    │     generates personalised invitation email + 5–7 tailored questions
    │     HR reviews/edits → approve triggers SMTP send
    │     generate_ics() produces .ics calendar file after scheduling
    │
    └─▶ Agent 6: ML Predictor (ml_agent.py)
          NL query → gpt-4o-mini parses intent → runs fit/join model predictions
          SHAP TreeExplainer computes per-candidate feature contributions
          streams NDJSON: results (with explanations) first, then LLM narrative summary
          POST /api/ml/predict
```

Every OpenAI call fires `agent_telemetry.fire_run()` as a background task — written to the `agent_runs` table with latency, token counts, prompt version, and agent-specific quality metrics. The analytics agent (`ANALYTICS_PROMPT_VERSION = "analytics-v1"`) now also records `sql_passed_validation`, `sql_blocked_reason`, `rows_returned`, and `has_session_context`. JD revision records `draft_version`. ML predictor records `prediction_type`, `candidate_count`, `shap_explanations`.

### Request Flow

1. JWT validated against `/api/auth/me` on every frontend mount
2. Every chat message → `POST /analytics/route` (supervisor) → dispatch
3. JD lifecycle: `drafting → pending_approval → approved → publishing → published`
   - Published JDs can be reverted to `pending_approval` via `POST /api/jd/revert` for edits and republishing
4. Candidate lifecycle: `Applied → AI Screened → Shortlisted → Interview Scheduled`
5. Supervisor routing receives full session context: `session_id`, `job_title`, `job_department`, `pipeline_state`, `history`

### Conversation Caching (Redis)

`app/core/redis.py` manages two Redis namespaces:

- **Chat history** — `conversation:{session_id}` (list, 24-hour TTL). On cache miss, falls back to Postgres `chat_messages`. `push_message` / `get_history` fail silently with a log warning — Redis is optional.
- **Active session** — `active_session:{user_id}` (string, 30-day TTL). Persists the last JD session the user had open so it can be restored on page refresh. Managed via `PUT/GET/DELETE /api/auth/active-session`; the frontend calls these on session change, dashboard nav, and logout. Replaces the previous localStorage approach.

### SQL Safety (Analytics Agent)

`app/services/sql_ast_validator.py` uses `sqlglot` to parse and walk the AST before executing any NLP-generated SQL. Blocks: non-SELECT statements, forbidden DML/DDL nodes, dangerous PostgreSQL functions (`pg_read_file`, `dblink`, etc.), unknown tables, and stacked queries. Belt-and-suspenders regex runs before the AST parse — trailing semicolons are stripped before the regex check to avoid false positives on valid single-statement queries.

Analytics responses are sanitised at two layers:
- `_sanitise_output()` strips UUID and email patterns from the narrated answer before it reaches the frontend.
- `_sanitise_sql_for_display()` replaces UUID/email literals in the SQL shown in the "View SQL" badge — the SQL that is actually executed is unaffected.

The `_FORMAT_SYSTEM` prompt also instructs the model to never reference raw database identifiers and to write in plain conversational English. No NeMo Guardrails framework is used.

`_resolve_session_context()` looks up the active `JDRequest` by `session_id` and injects the real `request_id` and `title` into the SQL generation prompt, so queries like "how many candidates applied for this job?" produce correct WHERE clauses rather than placeholder titles.

### Email (SMTP)

`app/services/email_sender.py` sends three email types: interview invitations, password reset links, and application confirmations. All calls return `False` (not raise) when `SMTP_HOST` is empty. For local dev, docker-compose runs Mailhog at `localhost:1025`; web UI at `localhost:8025`.

### Platform Publishing

- **Internal job board** — always live at `/jobs` (frontend route) once `status = "published"`; no credentials needed
- **LinkedIn** — UGC Posts API; requires `LINKEDIN_ACCESS_TOKEN` + `LINKEDIN_AUTHOR_URN`. Without credentials: demo mode returns a fake URL, no real API call
- **Indeed UK** — XML feed written to `indeed_feeds/` at `/indeed-feed/{id}.xml`; feed is always generated; `INDEED_PUBLISHER_ID` only needed to ping re-crawl
- **Google Jobs** — schema.org JSON-LD page at `job_pages/` served at `/jobs/{id}`; page is always generated; `GOOGLE_SERVICE_ACCOUNT_JSON` only needed to ping the Indexing API

All three external platforms fail gracefully when credentials are absent.

**Publish commit pattern** — `POST /api/jobs/post/{session_id}` streams NDJSON via `StreamingResponse`. The final DB writes (`req.status = "published"`, `JobPosting` rows) happen inside the async generator using a **fresh `AsyncSessionLocal()` session**, not the request-scoped `db`. This is intentional: the request-scoped session lifecycle can end before the generator finishes, causing the commit to silently fail.

### ML Models

Two GradientBoosting classifiers trained on IBM HR Analytics + synthetic negatives:

- **Fit model** (`ml_models/fit_model.joblib`) — predicts hire probability from screening score, skill overlap, seniority, etc. CV ROC-AUC 0.991.
- **Join model** (`ml_models/join_model.joblib`) — predicts offer-acceptance probability from interview format, days to respond, etc. CV ROC-AUC 0.879.

Both are lazy-loaded at first call by `ml_predictor.py`. Each model is saved as a dict bundle `{"pipeline": sklearn.Pipeline, "features": [...]}` — not the pipeline directly, because `feature_names_in_` is read-only on Pipeline. The pipeline is `StandardScaler → GradientBoostingClassifier`.

**SHAP explainability** — `explain_fit()` and `explain_join()` in `ml_predictor.py` use `shap.TreeExplainer` on the GBT step. Input is pre-processed through the StandardScaler before SHAP runs. Returns top 5 features sorted by absolute contribution as `[{feature, label, contribution, direction, raw_value}]`. Human-readable labels are defined in `_FIT_LABELS` / `_JOIN_LABELS` dicts. LIME is not used — it does not support Python 3.13. The `shap` package is installed via `uv pip install shap --python .venv/bin/python3`.

Explanations are attached to every `results` NDJSON event from the ML agent and rendered in the chat UI as collapsible "Why this score?" factor bars (`MlResultCard` in `ChatMessage.tsx`). Green bars = pushed score up, red = pushed it down.

Training data prep: `Data/prepare_kaggle_data.py` (IBM HR Analytics + 700 synthetic negatives per model).
Re-train: `PYTHONPATH=backend python backend/ml_train.py --source csv --csv-path Data/combined_dataset.csv`

ML outcome labels are recorded by HR via `POST /api/candidates/applications/{id}/outcome` after a hiring decision. These populate `outcome`, `offer_accepted`, etc. on `CandidateApplication` for future training.

### PII / Auth

- Emails stored encrypted (Fernet) + SHA-256 blind index for lookup
- Passwords bcrypt-hashed
- JWT (HS256) carries role (`hr`|`hm`) for RBAC; `get_current_user` / `require_role` FastAPI deps in `app/core/dependencies.py`
- CV files served only to authenticated HR from `cv_uploads/`

## Database Models

```
AgentRun              — one record per OpenAI call (agent_name, operation, prompt_version,
                        model, status, latency_ms, input/output tokens, metrics JSON)
User                  — email_hash (SHA-256), email_encrypted (Fernet), bcrypt password, role
JDRequest             — session_id, title, dept, location, salary_band, skills, status,
                        published_at, expires_at, max_applications
JDDraft               — request_id, version, content, rejection_feedback
ChatMessage           — request_id, role (user|assistant), content
PastJD                — title, dept, content, embedding vector(1536) for RAG
JobPosting            — request_id, platform, formatted_content, post_url, status
CandidateApplication  — name, email, phone, cover_letter (text), cover_letter_filename,
                        CV (filename + path), screening results (score 0–100,
                        recommendation, strengths/gaps JSON), shortlisted bool,
                        interview_status, interview_scheduled_at, format, location, notes,
                        outcome, outcome_recorded_at, offer_extended, offer_amount,
                        offer_date, offer_accepted, offer_declined_reason,
                        interview_rounds, days_to_respond
InterviewInvitation   — application_id, AI-generated email_subject/body/questions,
                        HR-approved final_recipient/subject/body, email_sent_at
```

## Migrations

Apply manually via docker after the initial Docker setup:

```bash
docker exec hiring_postgres psql -U hiring_user -d hiring_db \
  -f /docker-entrypoint-initdb.d/003_interview_scheduling.sql

# Or run SQL directly:
docker exec hiring_postgres psql -U hiring_user -d hiring_db \
  -c "ALTER TABLE ..."
```

Migration files in `backend/migrations/`:
- `001_init.sql` — auto-runs via Docker entrypoint
- `002_candidate_cv_screening.sql` — manual
- `003_interview_scheduling.sql` — manual
- `004_agent_runs.sql` — manual
- `005_ml_outcome_fields.sql` — adds outcome/offer/interview_rounds columns to `candidate_applications`
- `006_cover_letter_file.sql` — adds `cover_letter_filename` column to `candidate_applications`
- `007_job_expiry.sql` — adds `expires_at`, `max_applications`, `published_at` to `jd_requests`

## Key Architectural Conventions

- **All AI responses stream** — `jd_agent.py`, `job_poster_agent.py` use `async for chunk in stream`. The analytics agent streams NDJSON.
- **Telemetry is always fire-and-forget** — `asyncio.create_task(fire_run(...))` in every agent; never awaited inline.
- **RAG logs retrieval scores** — `rag.py` logs title + cosine similarity for every retrieved PastJD.
- **Supervisor falls back gracefully** — returns intent `other` on error or confidence < 0.5.
- **Frontend state machine** — `useJDSession.ts` drives the UI through `idle → drafting → pending_approval → approved → publishing → published`. Published JDs can be reverted via "Revise JD & Republish" button.
- **Session context flows to all agents** — `useJDSession` tracks `sessionTitle` and `sessionDepartment`; these are passed to the supervisor routing and analytics/ML endpoints on every request.
- **A2A agent cards** — `/.well-known/agents`, `/.well-known/jd-drafter/agent-card.json`, `/.well-known/job-poster/agent-card.json`, `/.well-known/ml-predictor/agent-card.json` expose agents to external systems.
- **Cover letter upload** — candidates can type a cover letter OR upload a PDF/DOCX/TXT file. The backend extracts text via `_extract_sync` (same as CV screener) and stores it in the `cover_letter` text column; original filename goes in `cover_letter_filename`. The frontend uses a Write/Upload toggle in the application form.
- **Job expiry & application cap** — `POST /api/jobs/post/{session_id}` accepts `expires_at` (ISO date) and `max_applications` (int). Jobs stop accepting applications when either threshold is hit; both are checked at query time and at submission time. The `max_applications` cap filter is applied in SQL (not Python post-processing) so `OFFSET`/`LIMIT` pagination works correctly.
- **Job board pagination** — `GET /api/candidates/jobs` accepts `page` (default 1) and `page_size` (default 10, max 100) query params; returns `{ jobs, total, page, page_size, total_pages }`. The frontend (`JobBoardPage`) paginates with prev/next + numbered page buttons and a "Showing X–Y of N roles" counter.
- **JD structured fields sync** — `jd_requests.location` and `jd_requests.salary_band` are updated whenever a new `JDDraft` is saved (both the rejection-revision path and the chat path). `_parse_location_salary()` in `routes/jd.py` extracts these from the draft markdown using section-header regex.
- **Chat → draft promotion** — the `/jd/chat` endpoint saves the agent reply as a new `JDDraft` version when the reply looks like a full JD: contains `##` headers, starts with `#` and is >300 chars, or contains `**Job Title` / `**About the Company` bold-label sections. This ensures approval and the job board always see the latest chat-revised content.
- **Stream sentinel buffering** — `readDraftStream()` in `api/jd.ts` buffers the tail of each streaming response so the `__SESSION_ID__` sentinel is never rendered in the chat UI even if it arrives split across TCP chunks.
- **Analytics output guardrail** — Two sanitisation functions: `_sanitise_output()` strips UUIDs/emails from narrated text; `_sanitise_sql_for_display()` redacts them from the SQL badge. Execution SQL is never altered. No NeMo Guardrails framework is used.
- **Analytics session context** — `_resolve_session_context()` in `analytics_agent.py` resolves the active session's real `request_id` and `title` and injects them into the SQL prompt so "this job" / "this role" references produce correct WHERE clauses.
- **Context window per agent** — Supervisor caps history at `history[-6:]`. JD agents (`stream_chat_reply`, `stream_revision`) pass full unbounded history via `messages.extend(history)` — no sliding window yet. RAG references are each truncated to 1 200 chars. Analytics fetches at most 50 DB rows and passes the first 20 to the formatter.
- **ML results rendered in chat** — `results` NDJSON events from the ML agent are attached to the assistant message as `mlData: MlResult[]`. `MlResultCard` in `ChatMessage.tsx` renders score gauges (Screen / Fit / Join) and collapsible SHAP factor bars per candidate. The `results` event arrives before the text chunks so the UI can render cards immediately.
- **Prompt versions** — every agent has a hardcoded `*_PROMPT_VERSION` constant (`jd-v1`, `supervisor-v1`, `analytics-v1`, `screen-v1`, `ml-agent-v1`) written to `agent_runs`. These must be manually incremented when prompts change — there is no automatic versioning.

### Agent Quality Telemetry

`GET /api/telemetry/quality?days=30` — aggregates `agent_runs` + `jd_drafts` + `candidate_applications` into a single quality report. Requires JWT. Returns:

- **routing** — intent distribution, per-intent avg confidence, low-confidence count
- **drafting** — avg draft versions before approval (from `jd_drafts.version` at approval time), off-topic block rate from chat
- **screening** — recommendation breakdown with score min/avg/max, score bucket distribution (0–39 / 40–59 / 60–79 / 80–100)
- **analytics** — SQL pass rate, blocked count, SQL execution errors, avg rows returned
- **ml** — prediction type mix, avg candidates per query, total SHAP explanations generated
- **errors** — per-agent error rate %
- **latency** — avg + p95 per agent/operation
- **daily_trend** — 14-day rolling run + error volume per agent

The `QualityPanel` component in `frontend/src/components/dashboard/QualityPanel.tsx` fetches this on dashboard mount and renders stat cards + bar charts. Empty state is shown until the platform has been used. The panel is rendered below the feature cards in `DashboardHome.tsx`.

## MCP Server

FastMCP stdio server at `backend/hiring_mcp/server.py` — exposes DB tools and platform posting tools for Claude Desktop or external agents.

```bash
PYTHONPATH=backend python backend/hiring_mcp/server.py
```

## What Is Not Yet Built

- Candidate portal (application status, round feedback)
- HM / HR separate dashboards
- Offer letter generation (out of scope V1)
- RAGAS live evaluation wired into CI (currently run manually)