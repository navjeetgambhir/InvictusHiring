# Invictus Hiring — Capstone Project

AI-powered hiring automation platform with human-in-the-loop for JD drafting, candidate shortlisting, and interview coordination.

## Project Structure

```
Capstone/
├── backend/                  # FastAPI Python backend
│   ├── app/
│   │   ├── main.py           # App entry point, CORS, HTTP logging, demo user seeding on startup
│   │   ├── core/
│   │   │   ├── config.py     # Pydantic settings (reads from backend/.env)
│   │   │   ├── database.py   # Async SQLAlchemy engine + session factory
│   │   │   ├── logging.py    # Loguru setup + stdlib → loguru intercept bridge
│   │   │   ├── security.py   # Fernet email encryption, SHA-256 blind index, bcrypt passwords, HS256 JWT
│   │   │   └── dependencies.py  # get_current_user / require_role FastAPI dependencies
│   │   ├── db/
│   │   │   ├── models.py     # User, PastJD, JDRequest, JDDraft, ChatMessage, JobPosting, CandidateApplication
│   │   │   └── queries.py    # Shared DB helpers: get_request_or_404, latest_draft
│   │   ├── services/
│   │   │   ├── supervisor.py        # Supervisor orchestration layer — RoutingDecision dataclass,
│   │   │   │                        #   supervisor_route() uses gpt-4o-mini to classify 7 intents
│   │   │   │                        #   (jd_draft, jd_chat, jd_revise, approve, publish, analytics, other)
│   │   │   │                        #   with pipeline_state + history context; falls back on low confidence
│   │   │   ├── jd_agent.py          # OpenAI streaming: extract_requirements, draft, revise, chat
│   │   │   ├── rag.py               # pgvector cosine similarity retrieval + OpenAI embeddings;
│   │   │   │                        #   logs retrieval scores per result (title + similarity)
│   │   │   ├── job_poster_agent.py  # Agent 2 — reformat JD per platform + stream NDJSON progress
│   │   │   ├── cv_screener.py       # CV text extraction (PDF/DOCX) + OpenAI candidate screening agent
│   │   │   └── platforms/
│   │   │       ├── linkedin.py      # LinkedIn UGC Posts API (ugcPosts endpoint)
│   │   │       ├── indeed.py        # Indeed XML feed generation + optional re-index ping
│   │   │       └── google_jobs.py   # schema.org JSON-LD page + Google Indexing API notify
│   │   └── api/routes/
│   │       ├── jd.py          # All JD drafter API endpoints; GET /api/jd/sessions with last_message_preview
│   │       ├── auth.py        # POST /api/auth/login, GET /api/auth/me, POST /api/auth/forgot-password
│   │       ├── analytics.py   # NLP-to-SQL analytics agent; POST /analytics/route for supervisor routing
│   │       ├── jobs.py        # POST /api/jobs/post/{id}, GET /api/jobs/postings/{id}, XML/HTML feeds
│   │       ├── candidates.py  # Public job board + apply endpoints; HR applications + CV download
│   │       └── agent_cards.py # A2A-compliant agent cards at /.well-known/*
│   ├── hiring_mcp/
│   │   ├── server.py   # FastMCP stdio server — DB, LinkedIn, Indeed, Google Jobs tools
│   │   └── client.py
│   ├── cv_uploads/           # Uploaded candidate CVs (UUID-named, served only to authenticated HR)
│   ├── tests/                # pytest test suite (37 tests, no real DB/OpenAI)
│   ├── migrations/
│   │   ├── 001_init.sql      # CREATE EXTENSION vector (run once)
│   │   └── 002_candidate_cv_screening.sql  # CV + screening columns on candidate_applications
│   ├── indeed_feeds/         # Generated Indeed XML files (served at /indeed-feed/{id}.xml)
│   ├── job_pages/            # Generated Google Jobs HTML pages (served at /jobs/{id})
│   ├── logs/                 # Loguru output (hiring.log, JSON, daily rotation)
│   └── .env                  # Local secrets — never commit
├── frontend/                 # React + Vite + TypeScript + shadcn/ui
│   └── src/
│       ├── App.tsx           # Root — JWT token validation on mount (GET /api/auth/me),
│       │                     #   view state: 'dashboard' | 'jd-chat', breadcrumb nav in header
│       ├── api/
│       │   ├── jd.ts         # Fetch wrappers for all JD endpoints (streaming-aware);
│       │   │                 #   fetchSessions() → SessionSummary[] with last_message_preview
│       │   ├── auth.ts       # login(), getStoredUser(), getToken(), clearUser()
│       │   ├── analytics.ts  # routeMessage() → RoutingDecision; calls POST /analytics/route
│       │   ├── agents.ts     # fetchAgentCard() — A2A agent card discovery
│       │   └── candidates.ts # fetchJobs, fetchJob, submitApplication (FormData), fetchApplications
│       ├── pages/
│       │   ├── JobBoardPage.tsx    # Public candidate job board — search + job cards
│       │   └── JobDetailPage.tsx   # Public job detail + CV upload apply form
│       ├── hooks/
│       │   └── useJDSession.ts  # State machine: idle→drafting→pending_approval→approved→publishing→published
│       │                        #   Uses routeMessage() for context-aware dispatch (pipeline_state + history)
│       │                        #   loadSession() restores past sessions from DB; sql badge support
│       └── components/
│           ├── auth/
│           │   └── LoginPage.tsx        # Split layout: left lavender/purple panel (InvictusLogo SVG,
│           │                            #   feature list, decorative blobs) + right login form;
│           │                            #   ForgotPassword sub-component; demo account auto-fill
│           ├── dashboard/
│           │   └── DashboardHome.tsx    # Post-login landing: 6 task cards + chat textarea + send button
│           │                            #   + 4 suggestion chips; cards above chat bar
│           ├── jd/
│           │   ├── JDChat.tsx           # Main chat interface with status header
│           │   ├── ChatMessage.tsx      # Bubble renderer — user/assistant/system + streaming cursor;
│           │   │                        #   SqlBadge with viewport-aware popover (flips up when near page bottom)
│           │   ├── SessionSidebar.tsx   # Chat session history with folder organisation;
│           │   │                        #   Folder (localStorage), SessionRow with status dot + ⋯ menu,
│           │   │                        #   FolderSection (collapsible, inline rename/delete), ungrouped sessions
│           │   ├── ApprovalBar.tsx      # Approve / Reject-with-feedback panel
│           │   ├── PublishingPanel.tsx  # Post-approval publishing progress (per-platform status + links)
│           │   ├── ApplicationsPanel.tsx # HR view: candidate list, AI scores, CV download, expand detail
│           │   └── RequirementsForm.tsx # Structured JD requirements form
│           ├── layout/
│           │   └── PageShell.tsx        # Shared candidate-facing page shell (header + main wrapper)
│           └── ui/                      # shadcn primitives: Button, Card, Input, Textarea, Badge, Label
├── Data/
│   ├── scrape_indeed.py  # Indeed scraper for seeding past JDs
│   ├── scrapper.py
│   └── seed_past_jds.py  # Seeds past_jds table with embeddings for RAG
├── docker-compose.yml        # PostgreSQL 17 + pgvector container
├── pytest.ini                # asyncio_mode=auto, testpaths=backend/tests
└── pyproject.toml            # uv-managed Python deps
```

## Running the App

```bash
# 1. Start the database
docker compose up -d

# 2. Start the backend (auto-reloads on file changes)
cd /Users/navjeetkaur/Desktop/Capstone
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000

# 3. Start the frontend
cd frontend && npm run dev -- --port 3000
```

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

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
RAG_TOP_K=5
RAG_SIMILARITY_THRESHOLD=0.75

# Auth
ENCRYPTION_KEY=<fernet-key>   # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
JWT_SECRET_KEY=<random-string>
JWT_EXPIRE_MINUTES=480

# Job board integrations (all optional — app works without them)
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_AUTHOR_URN=           # e.g. urn:li:person:ABC123 or urn:li:organization:12345
INDEED_PUBLISHER_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=   # full JSON of GCP service account key file (as string)
APP_BASE_URL=http://localhost:8000
```

## Running Tests

```bash
cd /Users/navjeetkaur/Desktop/Capstone
.venv/bin/pytest -v
# 37 tests — no real DB or OpenAI calls, all mocked
```

## API Endpoints

### Auth
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/login` | Email + password → JWT access token |
| `GET`  | `/api/auth/me` | Returns authenticated user profile; used for token validation on mount |
| `POST` | `/api/auth/forgot-password` | Accepts email, always returns 200 (prevents enumeration); logs if user found |

### JD Drafter (Agent 1)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jd/draft-freetext` | Free-text requirements → extracts fields via OpenAI function calling → streams JD draft |
| `POST` | `/api/jd/draft` | Structured requirements → streams JD draft |
| `POST` | `/api/jd/chat` | Free-form chat to refine current draft (streams) |
| `POST` | `/api/jd/approve` | `approved=true` → marks approved; `approved=false` + feedback → agent revises (streams) |
| `GET`  | `/api/jd/sessions` | All sessions for authenticated user, newest first, with last_message_preview |
| `GET`  | `/api/jd/session/{id}` | Returns session state, latest draft, and full chat history |

### Analytics / Supervisor
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/analytics/query` | NLP → SQL → result (streams) |
| `POST` | `/analytics/route` | Supervisor routing — returns `RoutingDecision` (intent, confidence, reasoning, suggested_action) |

### Job Poster (Agent 2)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs/post/{session_id}` | Reformat approved JD for each platform + publish; streams NDJSON progress |
| `GET`  | `/api/jobs/postings/{session_id}` | Returns all platform posting records for a session |
| `GET`  | `/api/jobs/indeed-feed/{session_id}.xml` | Serves Indeed XML feed (crawled by Indeed) |
| `GET`  | `/api/jobs/jobs/{session_id}` | Serves Google Jobs HTML page with schema.org JSON-LD |

### Candidate Job Board (public)
| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/candidates/jobs` | All published JDs (no auth) |
| `GET`  | `/api/candidates/jobs/{session_id}` | Single published job detail (no auth) |
| `POST` | `/api/candidates/apply/{session_id}` | Submit application — multipart form with optional CV upload (no auth) |

### Candidate Applications (HR/HM only)
| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/candidates/applications/{session_id}` | All applications for a session with AI screening results |
| `GET`  | `/api/candidates/applications/{session_id}/cv/{application_id}` | Download candidate CV |

### Agent Discovery (A2A)
| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/.well-known/agents` | Agent registry — lists all hosted agents |
| `GET`  | `/.well-known/jd-drafter/agent-card.json` | A2A agent card for JD Drafter |
| `GET`  | `/.well-known/job-poster/agent-card.json` | A2A agent card for Job Poster |

### Other
| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check |

## Key Flows

### JD Drafting — Agent 1 (implemented)
1. User logs in (JWT auth); token validated against `/api/auth/me` on mount
2. Dashboard shown first (`DashboardHome`) — 6 task cards + chat bar + suggestion chips
3. User types a job description in plain English
4. Supervisor routes to `jd_draft` intent → `POST /api/jd/draft-freetext`
5. OpenAI function calling extracts structured fields (title, dept, location, salary, skills)
6. pgvector RAG retrieves similar past JDs from `past_jds` table (cosine similarity, `text-embedding-3-small`); retrieval scores logged per result
7. OpenAI streams a full UK-compliant JD draft back to the chat
8. HR/HM can refine via chat or approve/reject with feedback
9. On rejection: agent auto-revises with feedback, increments draft version
10. On approval: `status = "approved"` → PublishingPanel appears

### Supervisor Routing (implemented)
- Every user message is first sent to `POST /analytics/route`
- Supervisor uses `gpt-4o-mini` with JSON response to classify into 7 intents: `jd_draft`, `jd_chat`, `jd_revise`, `approve`, `publish`, `analytics`, `other`
- Routing considers `pipeline_state` (current JD status), `has_draft`, and recent chat history for context-aware decisions
- Falls back to `other` on error or confidence < 0.5

### Job Posting — Agent 2 (implemented)
1. HR clicks "Publish to Job Boards" in the PublishingPanel
2. `POST /api/jobs/post/{session_id}` triggers the Job Poster agent
3. For each platform (LinkedIn, Indeed UK, Google Jobs), OpenAI reformats the JD with platform-specific tone/structure/limits
4. Each formatted JD is published to the real platform API (falls back gracefully if credentials not set)
5. Progress streams as NDJSON: `start → chunk → posted → done`
6. JobPosting records saved to DB; JD status moves to `published`

**Platform publishing mechanisms:**
- **LinkedIn** — UGC Posts API (`POST /v2/ugcPosts`); requires `LINKEDIN_ACCESS_TOKEN` + `LINKEDIN_AUTHOR_URN`
- **Indeed UK** — XML job feed written to `indeed_feeds/` and served at `/indeed-feed/{id}.xml`; optionally pings Indeed Employer API to re-index
- **Google Jobs** — schema.org/JobPosting JSON-LD page written to `job_pages/` and served at `/jobs/{id}`; optionally calls Google Indexing API for fast crawl

### Candidate Job Board (implemented)
1. Published JDs appear at `http://localhost:3000/jobs` — no login required
2. Candidates click a role → full JD detail + apply form at `/jobs/{session_id}`
3. Apply form: name, email, phone (optional), CV upload (PDF/DOCX/TXT, max 5 MB), cover letter
4. `POST /api/candidates/apply/{session_id}` — saves application, triggers background CV screening
5. CV screener extracts text (pypdf / python-docx) then calls OpenAI to score against job requirements
6. Screening result (0–100 score, recommendation, strengths, gaps) saved to `candidate_applications`
7. HR sees ApplicationsPanel in the dashboard once a JD is published — lists all applicants with AI scores, CV download, and full screening breakdown; polls every 10 s while any application is still being screened

### Interview Scheduling — not yet built
### Offer Letter — out of scope for V1

## Database Models

```
User                  — application user (email_hash SHA-256, email_encrypted Fernet, bcrypt password, role: hr|hm)
JDRequest             — one per submission (session_id, submitted_by, role, title, dept, location, salary_band,
                        required_skills, nice_to_have_skills, company_description, status)
JDDraft               — one per draft version (request_id, version, content, rejection_feedback)
ChatMessage           — chat history (request_id, role: user|assistant, content)
PastJD                — historical approved JDs for RAG (title, dept, content, embedding: vector(1536))
JobPosting            — platform posting record (request_id, platform, formatted_content, post_url, status: posted|failed)
CandidateApplication  — candidate application (request_id, name, email, phone, cover_letter,
                        cv_filename, cv_path, screening_status: pending|screened|failed,
                        screening_score 0–100, screening_summary, screening_strengths JSON,
                        screening_gaps JSON, screening_recommendation: strong_match|good_match|partial_match|poor_match)
```

### JD Draft States
```
drafting → pending_approval → approved → publishing → published
```

### Candidate Pipeline States (planned)
```
Applied → AI Screened → HR Shortlist Review → HM Shortlist Review
→ Interview Scheduled → Interviewed → [Offer] → Hired / Rejected
```

## MCP Server (`backend/hiring_mcp/server.py`)

FastMCP stdio server exposing tools for external AI agents and Claude Desktop:

| Tool | Description |
|------|-------------|
| `db_list_sessions` | List recent JD sessions |
| `db_get_session` | Full session detail (request, draft, chat, postings) |
| `db_search_similar_jds` | pgvector cosine similarity search over past JDs |
| `db_get_postings` | Job posting records for a session |
| `linkedin_post_job` | Publish to LinkedIn UGC Posts API |
| `indeed_post_job` | Generate XML feed + optional re-index notify |
| `google_jobs_post_job` | Generate JSON-LD page + optional Indexing API notify |

Run standalone: `PYTHONPATH=backend python backend/hiring_mcp/server.py`

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.13, FastAPI, SQLAlchemy (async), asyncpg |
| AI | OpenAI (`gpt-4o`), function calling, streaming |
| Embeddings | `text-embedding-3-small` (1536 dims) |
| Vector DB | PostgreSQL 17 + pgvector 0.8.2 |
| ORM | SQLAlchemy 2.0 mapped columns |
| Auth | JWT (HS256 via python-jose), bcrypt passwords, Fernet email encryption |
| Logging | Loguru — console (coloured) + JSON file + stdlib intercept for SQLAlchemy |
| MCP | FastMCP stdio server (hiring_mcp/) |
| Frontend | React 19, Vite, TypeScript, Tailwind CSS v4, shadcn/ui, Radix UI |
| Fonts | Inter (Google Fonts, weights 300–700, loaded via index.html preconnect) |
| Testing | pytest, pytest-asyncio, pytest-mock, httpx (AsyncClient) |
| Infra | Docker Compose (postgres container), uv (Python deps) |

## Design Decisions

- **Free-text chat input** — no form; users describe the role in plain English, OpenAI extracts structured fields via function calling
- **Streaming first** — all AI responses stream chunk-by-chunk; frontend renders live with a blinking cursor
- **Human-in-the-loop** — every JD requires explicit HR approval before publishing; rejections trigger auto-revision with feedback
- **RAG on past JDs** — new drafts reference approved historical JDs for consistent tone and structure; stored in `past_jds` with pgvector embeddings; retrieval scores logged per result
- **Session-based** — each drafting session has a UUID, persists full chat history and all draft versions in Postgres
- **Supervisor orchestration** — every message is classified by a lightweight `gpt-4o-mini` supervisor before dispatch; routing is context-aware (pipeline state + history); falls back gracefully on low confidence
- **Two-agent pipeline** — Agent 1 (JD Drafter) feeds into Agent 2 (Job Poster); both expose A2A-compliant agent cards
- **PII-safe auth** — emails stored encrypted (Fernet) with a SHA-256 blind index for lookup; passwords bcrypt-hashed; JWT carries role for RBAC; token validated on every page mount via `/api/auth/me`
- **Graceful job board fallback** — all three platform integrations fail gracefully if credentials aren't configured; demo works without any API keys
- **Split login layout** — left panel (lavender/purple gradient, InvictusLogo SVG, feature list) + right login form; forgot-password flow built in; demo account auto-fill buttons
- **Dashboard-first UX** — after login, users see a task overview dashboard (`DashboardHome`) before entering any specific flow; chat bar on dashboard switches to JD chat view on send

## What Is Not Yet Built

- [x] Left sidebar — session history with folder grouping (implemented: `SessionSidebar.tsx`)
- [ ] Interview scheduling — Google Calendar self-scheduling link
- [ ] Candidate portal — application status, round feedback
- [ ] HM / HR separate dashboards
- [ ] Offer letter generation (out of scope V1)