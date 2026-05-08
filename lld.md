# Low-Level Design — Invictus Hiring AI Platform

## 1. System Overview

Invictus Hiring is a multi-agent AI platform that automates the full hiring funnel: JD drafting → job board publishing → candidate screening → interview scheduling. All AI responses stream in real time. Human-in-the-loop approval gates sit at JD approval and interview email dispatch.

---

## 2. Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI (Python 3.12), async/await throughout |
| ORM | SQLAlchemy 2.0 (async), Mapped/mapped_column |
| Database | PostgreSQL 16 + pgvector extension |
| Cache | Redis (chat history, 24 h TTL) |
| AI | OpenAI GPT-4o (agents), GPT-4o-mini (supervisor, SQL gen) |
| ML | scikit-learn GradientBoosting (fit + join models) |
| Embeddings | OpenAI text-embedding-3-small (1536 dims, pgvector) |
| Tracing | LangSmith (every agent call wrapped via `wrap_openai`) |
| Auth | JWT HS256 + bcrypt passwords + Fernet email encryption |
| Email | SMTP / Mailhog (local dev) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui |
| Container | Docker Compose (postgres, redis, mailhog) |

---

## 3. Database Schema

### 3.1 Entity-Relationship Summary

```
User (1) ──────────────────── (N) JDRequest
JDRequest (1) ─────────────── (N) JDDraft
JDRequest (1) ─────────────── (N) ChatMessage
JDRequest (1) ─────────────── (N) JobPosting
JDRequest (1) ─────────────── (N) CandidateApplication
CandidateApplication (1) ──── (N) InterviewInvitation
PastJD ─── (standalone, used for RAG only)
AgentRun ─ (standalone audit log)
```

### 3.2 Table Definitions

#### `users`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| email_hash | VARCHAR(64) UNIQUE | SHA-256 blind index for lookup |
| email_encrypted | TEXT | Fernet ciphertext |
| name | VARCHAR(255) | |
| role | VARCHAR(50) | `hr` \| `hm` |
| hashed_password | VARCHAR(255) | bcrypt |
| created_at | TIMESTAMPTZ | |

#### `jd_requests`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | internal FK target |
| session_id | UUID INDEXED | exposed to frontend |
| submitted_by | VARCHAR | user email |
| role | VARCHAR | `hr` \| `hm` |
| title, department, location, salary_band | VARCHAR | job metadata |
| required_skills, nice_to_have_skills | JSON | string arrays |
| company_description, additional_context | TEXT | |
| status | VARCHAR(50) | `drafting → pending_approval → approved → publishing → published` |
| published_at, expires_at | TIMESTAMPTZ nullable | job board visibility window |
| max_applications | INT nullable | auto-close threshold |
| created_at | TIMESTAMPTZ | |

#### `jd_drafts`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| request_id | UUID FK → jd_requests | |
| version | INT | increments on each revision |
| content | TEXT | full markdown JD text |
| rejection_feedback | TEXT nullable | feedback that triggered this revision |
| prompt_version | VARCHAR(50) | e.g. `jd-v1` for prompt drift tracking |

#### `chat_messages`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| request_id | UUID FK → jd_requests | |
| role | VARCHAR(20) | `user` \| `assistant` |
| content | TEXT | |
| created_at | TIMESTAMPTZ | |

#### `job_postings`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| request_id | UUID FK → jd_requests | |
| platform | VARCHAR(50) | `linkedin` \| `indeed` \| `google_jobs` |
| formatted_content | TEXT | platform-reformatted JD |
| post_url | VARCHAR(500) nullable | live URL after posting |
| status | VARCHAR(20) | `posted` \| `failed` |
| posted_at | TIMESTAMPTZ | |

#### `candidate_applications`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| request_id | UUID FK → jd_requests | |
| name, email, phone | VARCHAR | |
| cover_letter | TEXT nullable | typed or extracted from uploaded file |
| cover_letter_filename | VARCHAR(255) nullable | original filename if uploaded |
| cv_filename, cv_path | VARCHAR | stored in `cv_uploads/` |
| screening_status | VARCHAR(20) | `pending → screened \| failed` |
| screening_score | INT | 0–100 |
| screening_summary | TEXT | |
| screening_strengths, screening_gaps | JSON | string arrays |
| screening_recommendation | VARCHAR(50) | `strong_match \| good_match \| partial_match \| poor_match` |
| shortlisted | BOOLEAN | |
| interview_status | VARCHAR(20) nullable | `scheduled \| completed \| cancelled` |
| interview_scheduled_at | TIMESTAMPTZ nullable | |
| interview_format | VARCHAR(20) nullable | `phone \| video \| in_person` |
| interview_location | VARCHAR(500) nullable | |
| outcome | VARCHAR(20) nullable | `hired \| rejected \| withdrew \| no_hire` |
| offer_extended, offer_accepted | BOOLEAN nullable | |
| offer_amount | VARCHAR(100) nullable | |
| interview_rounds, days_to_respond | SMALLINT nullable | ML training features |
| applied_at | TIMESTAMPTZ | |

#### `interview_invitations`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| application_id | UUID FK → candidate_applications | |
| email_subject, email_body | TEXT | AI-generated draft |
| interview_questions | JSON | 5–7 tailored questions |
| final_recipient, final_subject, final_body | TEXT nullable | HR-edited version |
| email_approved_at, email_sent_at | TIMESTAMPTZ nullable | |
| email_send_error | TEXT nullable | |

#### `past_jds`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| title, department | VARCHAR | |
| content | TEXT | historical JD for RAG |
| embedding | vector(1536) | pgvector; cosine similarity search |

#### `agent_runs`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| agent_name | VARCHAR(50) | `jd_drafter \| cv_screener \| supervisor \| job_poster` |
| operation | VARCHAR(50) | `initial_draft \| revision \| chat \| route \| screen \| post` |
| prompt_version | VARCHAR(50) | |
| model | VARCHAR(100) | |
| status | VARCHAR(20) | `success \| error` |
| session_id, application_id | UUID nullable | links for traceability |
| latency_ms, input_tokens, output_tokens | INT nullable | |
| metrics | JSON nullable | agent-specific eval data |
| error_message | TEXT nullable | |

---

## 4. API Routes

### Auth — `/api/auth`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/register` | Create user (bcrypt password, Fernet email) |
| POST | `/login` | Validate credentials → JWT |
| GET | `/me` | Validate JWT → return user profile |

### JD Drafter — `/api/jd`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/draft-freetext` | Extract structured fields from free text → stream JD draft |
| POST | `/draft` | Structured form submit → stream JD draft |
| POST | `/chat` | Conversational JD refinement → stream reply |
| POST | `/approve` | Approve (→ `approved`) or reject with feedback (→ stream revision) |
| POST | `/revert` | Revert published/approved JD back to `pending_approval` for re-editing |
| GET | `/sessions` | List all sessions for authenticated user |
| GET | `/session/{session_id}` | Full session state: status, latest draft, chat history |

### Job Publishing — `/api/jobs`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/post/{session_id}` | Publish approved JD to all platforms; streams NDJSON progress |
| GET | `/postings/{session_id}` | List platform posting records |
| GET | `/indeed-feed/{session_id}.xml` | Serve Indeed XML feed |
| GET | `/jobs/{session_id}` | Serve Google Jobs schema.org HTML page |

### Candidates — `/api/candidates`
| Method | Path | Description |
|--------|------|-------------|
| GET | `/jobs?page=1&page_size=10` | Public paginated job board (filters expired + full jobs); returns `{jobs, total, page, page_size, total_pages}` |
| GET | `/jobs/{session_id}` | Public single job detail |
| POST | `/apply/{session_id}` | Submit application (multipart: CV + optional cover letter file) |
| GET | `/applications/{session_id}` | HR: list applications with screening results |
| GET | `/applications/{session_id}/cv/{application_id}` | HR: download CV file |
| POST | `/applications/{id}/outcome` | HR: record hiring outcome for ML training |

### Interviews — `/api/interviews`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/shortlist/{application_id}` | Toggle shortlist flag |
| POST | `/generate/{application_id}` | Generate AI invitation email + questions |
| POST | `/approve-email/{invitation_id}` | HR approves/edits → triggers SMTP send |
| POST | `/schedule/{application_id}` | Record interview schedule |
| GET | `/session/{session_id}` | List all interview records for a JD session |
| GET | `/ics/{application_id}` | Download iCal `.ics` file |

### Analytics — `/api/analytics`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/route` | Supervisor routing: classifies message intent + session context |
| POST | `/classify` | Simple 3-class intent classifier |
| POST | `/query` | NLP → SQL → execute → stream natural language answer (NDJSON) |

### ML Predictions — `/api/ml`
| Method | Path | Description |
|--------|------|-------------|
| POST | `/predict` | NL question → fit/join model predictions → stream NDJSON |

---

## 5. Agent Architecture

### 5.1 Supervisor (gpt-4o-mini)

Routes every user message to the correct agent by returning a JSON routing decision:

```
{
  intent: jd_draft | jd_chat | jd_revise | approve | publish |
          analytics | ml_predict | other,
  confidence: 0.0–1.0,
  reasoning: "...",
  suggested_action: "...",
  secondary_intent: null | <intent>
}
```

Context injected per request: `pipeline_state`, `has_draft`, `session_id`, `job_title`, `job_department`, last 6 chat messages. Falls back to `other` if confidence < 0.5.

### 5.2 Agent 1 — JD Drafter (`jd_agent.py`)

**Flow:**
1. `extract_requirements()` — GPT-4o-mini parses free-text → structured JSON fields (title, location, salary_band, skills, etc.)
2. `retrieve_similar_jds()` — pgvector cosine similarity search against `past_jds` (top-K, threshold 0.75)
3. `stream_initial_draft()` — GPT-4o streams full JD, seeded with retrieved examples
4. `stream_chat_reply()` — conversational refinement with full chat history. If the reply looks like a full JD (contains `##` headers, starts with `#` and >300 chars, or contains `**Job Title`/`**About the Company` bold-label sections), it is saved as a new `JDDraft` version and `jd_requests.location`/`salary_band` are re-parsed and updated via `_parse_location_salary()`.
5. `stream_revision()` — structured revision on rejection feedback; always creates a new `JDDraft` version and updates structured fields.

**Structured field sync:** `jd_requests.location` and `jd_requests.salary_band` are set at draft creation from `extract_requirements()` and re-synced on every subsequent draft save. `_parse_location_salary()` (in `routes/jd.py`) uses section-header regex to extract these from the markdown content.

**RAG:** `app/services/rag.py` embeds the role title + skills using `text-embedding-3-small`, queries `past_jds` with `<=>` (cosine distance), logs retrieval scores.

### 5.3 Agent 2 — Job Poster (`job_poster_agent.py`)

Reformats the approved JD for each platform, then dispatches:
- **Internal job board** — always live at `/jobs` (frontend route) once `status = "published"`; no credentials needed
- **LinkedIn** — UGC Posts API (`/ugcPosts`); without credentials returns a demo URL (no real call)
- **Indeed UK** — generates XML feed saved to `indeed_feeds/{session_id}.xml`; served at `/api/jobs/indeed-feed/{id}.xml`; `INDEED_PUBLISHER_ID` only needed to ping re-crawl
- **Google Jobs** — generates schema.org JSON-LD HTML page saved to `job_pages/{session_id}.html`; served at `/api/jobs/jobs/{id}`; `GOOGLE_SERVICE_ACCOUNT_JSON` only needed to ping the Indexing API

Streams NDJSON progress events: `start → chunk → posted | error → done`. All external platforms fail gracefully when credentials are absent.

**DB commit pattern:** The `done` event handler inside the `StreamingResponse` generator uses a **fresh `AsyncSessionLocal()` session** (not the request-scoped `db`) for `req.status = "published"` and `JobPosting` inserts. The request-scoped session can be torn down before the generator finishes, causing a silent commit failure.

### 5.4 Agent 3 — CV Screener (`cv_screener.py`)

Triggered as a background task (`asyncio.create_task`) immediately after `POST /apply`. Never blocks the HTTP response.

**Flow:**
1. `_extract_sync()` — extracts text from PDF (pypdf), DOCX (python-docx), or plain text
2. GPT-4o scores the CV against the JD: 0–100 score, summary, strengths, gaps, recommendation
3. Writes result to `CandidateApplication.screening_*` columns

Same `_extract_sync()` is used for uploaded cover letter files.

### 5.5 Agent 4 — Analytics (`analytics_agent.py`)

**Flow:**
1. `_resolve_session_context()` — if `session_id` provided, looks up `JDRequest` and injects `request_id`, `title` into SQL prompt
2. GPT-4o-mini generates a PostgreSQL SELECT statement
3. `validate_sql()` — AST validation via sqlglot (see §6)
4. Execute against DB via SQLAlchemy `text()`
5. GPT-4o streams a natural language answer from the result rows
6. `_sanitise_output()` strips any UUID patterns from the narrated response before it reaches the frontend

### 5.6 Agent 5 — Interview Scheduler (`interview_agent.py`)

**Flow:**
1. HR shortlists a candidate → `POST /interviews/generate/{application_id}`
2. GPT-4o generates personalised email subject, body, and 5–7 tailored interview questions
3. HR reviews and optionally edits in the UI → `POST /interviews/approve-email/{invitation_id}`
4. Backend sends via SMTP and records `email_sent_at`
5. `generate_ics()` produces an `.ics` calendar attachment after scheduling

### 5.7 Agent 6 — ML Predictor (`ml_agent.py` + `ml_predictor.py`)

**Flow:**
1. GPT-4o-mini parses the NL question → extracts intent (fit score / join probability / ranking)
2. Queries `candidate_applications` for the target session's screened candidates
3. `ml_predictor.py` loads models lazily (joblib); runs `predict_proba()` for each candidate
4. Streams NDJSON: `results` chunk (structured predictions) then LLM narrative summary

**Models** (saved as `{"pipeline": Pipeline, "features": [...]}`):
- `fit_model.joblib` — hire probability, CV ROC-AUC 0.991
- `join_model.joblib` — offer-acceptance probability, CV ROC-AUC 0.879

---

## 6. SQL Safety Validator (`sql_ast_validator.py`)

Belt-and-suspenders approach — two independent layers:

**Layer 1 — Regex pre-check** (runs on trailing-semicolon-stripped SQL):
- Stacked SQL keywords after `;`
- Trailing `--` comments
- Block comments `/* */`
- `xp_cmdshell`
- `COPY ... TO`

**Layer 2 — sqlglot AST walk:**
1. Parse must succeed (catches syntax errors)
2. Exactly one statement
3. Root node must be `SELECT`
4. No forbidden node types anywhere in the tree: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`, `TRANSACTION`, `COMMIT`, `ROLLBACK`, `GRANT`, `REVOKE`
5. No dangerous functions: `pg_read_file`, `pg_ls_dir`, `pg_execute`, `dblink`, `COPY`, `lo_export`, `pg_sleep`, `current_setting`
6. All referenced table names must be in the known allowlist: `jd_requests`, `jd_drafts`, `chat_messages`, `job_postings`, `candidate_applications`, `users`, `past_jds`

Returns `ASTValidationResult(passed, violations, normalized_sql)`. The normalized SQL (sqlglot canonical form) is used for execution.

---

## 7. Authentication & Security

### JWT Flow
```
POST /auth/login
  → bcrypt.verify(password, hash)
  → create_access_token(sub=email_hash, role=role)
  → returns {access_token, token_type}

Every protected route:
  → Authorization: Bearer <token>
  → get_current_user() decodes JWT → looks up user by email_hash
  → injects CurrentUser into handler
```

### PII Protection
- Emails are never stored in plain text. On write: SHA-256 hash (blind index) + Fernet encryption stored separately.
- On read: decrypt with Fernet key from env.
- CV files stored at `cv_uploads/{filename}` and served only to authenticated HR via streaming `FileResponse`.

### RBAC
- `require_role("hr")` dependency blocks HM from HR-only endpoints (CV downloads, outcome recording).
- JWT carries `role` claim; validated on every request.

---

## 8. Conversation Caching (Redis)

```
Key:   conversation:{session_id}
Type:  Redis List (RPUSH / LRANGE)
TTL:   24 hours
Value: JSON-encoded {role, content} objects
```

On every JD chat message:
1. `get_history(session_id)` → Redis LRANGE
2. Cache miss → SQL query `chat_messages` ordered by `created_at` → `seed_history()` warms cache
3. After AI reply → `push_message(session_id, role, content)` on both user message and assistant reply

Redis is optional — both `push_message` and `get_history` catch all exceptions and log a warning rather than raising.

---

## 9. Streaming Protocol

### JD Draft Stream (plain text)
```
chunk1chunk2chunk3...chunkN\n\n__SESSION_ID__<uuid>
```
Frontend `readDraftStream()` buffers the last 50 characters to ensure the sentinel is never rendered as visible text even if it arrives split across TCP chunks.

### Analytics / ML Stream (NDJSON)
Each line is a complete JSON object:
```jsonl
{"type": "sql",     "sql": "SELECT ..."}
{"type": "chunk",   "text": "There are 3 candidates..."}
{"type": "done"}
{"type": "error",   "message": "..."}
```
ML adds a `results` event before the narrative chunks:
```jsonl
{"type": "results", "data": [{...}, ...]}
```

### Job Posting Stream (NDJSON)
```jsonl
{"type": "start",  "platform": "linkedin"}
{"type": "posted", "platform": "linkedin", "platform_id": "...", "url": "...", "content": "..."}
{"type": "error",  "platform": "indeed",   "message": "..."}
{"type": "done"}
```

---

## 10. Frontend State Machine (`useJDSession.ts`)

```
idle
 │  sendMessage (jd_draft intent)
 ▼
drafting ──────────────────────── stream error ──▶ error
 │  draft complete
 ▼
pending_approval
 │  approve()              │  reject(feedback)
 ▼                         ▼
approved              drafting (revision)
 │  publish()              │  revision complete
 ▼                         ▼
publishing         pending_approval
 │  all platforms done
 ▼
published
 │  revertForRevision()
 ▼
pending_approval  (re-enter approval → publish loop)
```

**Session context tracked in hook state:**
- `sessionId` — UUID string
- `sessionTitle` — job title (set on load or after first draft)
- `sessionDepartment` — department (same)
- `status` — current lifecycle state
- `postings` — per-platform posting status

All three context fields are forwarded to `routeMessage`, `streamAnalyticsQuery`, and `streamMlQuery` on every invocation.

---

## 11. Job Board — Candidate Flow

### Pagination
`GET /api/candidates/jobs` returns a paginated envelope:
```json
{ "jobs": [...], "total": 42, "page": 1, "page_size": 10, "total_pages": 5 }
```
The `max_applications` cap is applied in SQL (not Python post-processing) so `OFFSET`/`LIMIT` paginates the already-filtered set correctly. The frontend (`JobBoardPage`) renders prev/next + numbered page buttons with ellipsis for large page counts, and a "Showing X–Y of N roles" counter.

### Application Submission
```
POST /candidates/apply/{session_id}   (multipart/form-data)
  → check _is_accepting(): expires_at not past, application count < max_applications
  → save CV to cv_uploads/
  → if cover_letter_file: _extract_sync() → store text in cover_letter column
  → insert CandidateApplication (screening_status=pending)
  → asyncio.create_task(screen_candidate())   ← non-blocking
  → 201 Created
```

### Application Closure Logic
A job stops accepting applications when either condition is true:
- `expires_at` is set and `now() > expires_at`
- `max_applications` is set and `COUNT(applications) >= max_applications`

Both checked at list time (SQL WHERE clause) and at submit time (returns 409 if closed).

---

## 12. Telemetry (`agent_telemetry.py`)

Every agent call fires `fire_run()` as a background task:

```python
asyncio.create_task(fire_run(
    agent_name=...,
    operation=...,
    prompt_version=...,
    model=...,
    status="success"|"error",
    session_id=...,
    application_id=...,
    latency_ms=...,
    input_tokens=...,
    output_tokens=...,
    metrics={...},
))
```

Written to `agent_runs` table. Never awaited inline — telemetry failure never affects the user-facing response.

---

## 13. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Separate `session_id` from `id` on `JDRequest` | Frontend uses `session_id` (stable UUID exposed in URLs); `id` is internal FK target. Prevents sequential ID enumeration. |
| Redis for chat history | Avoids re-querying `chat_messages` on every message in a session. Falls back to DB gracefully. |
| sqlglot AST validator instead of NeMo Guardrails | Full AST walk catches obfuscation (case variations, comment injection) that regex-only approaches miss. No external framework dependency. |
| Background CV screening | Decouples slow PDF extraction + LLM call from the HTTP response. Candidate gets instant confirmation; screening updates asynchronously. |
| ML models saved as dict bundles | `{"pipeline": Pipeline, "features": [...]}` rather than raw Pipeline because `feature_names_in_` is read-only after fitting — can't attach extra metadata to the Pipeline object itself. |
| Fernet email encryption + SHA-256 blind index | Allows fast user lookup by email without ever storing plain-text PII. Blind index is constant-time comparable; actual value only decrypted when needed. |
| `__SESSION_ID__` sentinel buffered in frontend | The sentinel is appended at the end of a streaming JD draft response. Network fragmentation can split it across TCP chunks; the 50-char tail buffer in `readDraftStream()` ensures it is never displayed to the user. |
| Analytics output guardrail without NeMo | `_sanitise_output()` applies a UUID regex strip on every narrated chunk. The `_FORMAT_SYSTEM` prompt instructs the model to avoid raw IDs. Two independent layers: prompt instruction + post-processing. |
| Fresh session for publish commit | `POST /jobs/post/{session_id}` commits inside a `StreamingResponse` generator. FastAPI may close the request-scoped `db` session before the generator finishes. A fresh `AsyncSessionLocal()` inside the generator is not tied to the request lifecycle and commits reliably. |
| Chat reply promoted to JDDraft | The `/jd/chat` endpoint saves the reply as a new `JDDraft` version when it looks like a full JD. This ensures the approval endpoint and job board always read the latest revised content, not just the original draft. Detection uses `##` headers, `# Title` starts, or `**Job Title`/`**About the Company` bold-label sections (the format GPT-4o uses). |
| `max_applications` filter in SQL, not Python | Applying the cap in a Python `for` loop after `SELECT *` means `OFFSET`/`LIMIT` paginates the unfiltered set — the wrong records end up on each page. Moving the filter into the SQL `WHERE` clause makes pagination correct. |