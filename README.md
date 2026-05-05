# Invictus Hiring

AI-powered hiring automation platform with human-in-the-loop for JD drafting, candidate shortlisting, and interview scheduling.

---

## Features

| Agent | What it does |
|-------|--------------|
| **JD Drafter** (Agent 1) | Turns plain-English role descriptions into UK-compliant job descriptions via OpenAI function calling + pgvector RAG on past JDs |
| **Job Publisher** (Agent 2) | Reformats and posts approved JDs to LinkedIn, Indeed UK, and Google Jobs |
| **CV Screener** (Agent 3) | Extracts text from uploaded CVs and scores candidates 0–100 against job requirements |
| **Analytics** (Agent 4) | Answers natural-language questions about hiring data by generating and running safe SQL |
| **Interview Scheduler** (Agent 5) | Generates personalised AI invitation emails + tailored interview questions for shortlisted candidates; HR reviews and approves before sending |
| **Supervisor** | Routes every user message to the right agent based on pipeline state and conversation history |

**Human-in-the-loop at every stage** — JDs require explicit approval before publishing; invitation emails are editable and require HR sign-off before they are sent.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.0 (async), asyncpg |
| AI | OpenAI `gpt-4o` — function calling, streaming, JSON mode |
| Embeddings | `text-embedding-3-small` (1536 dims) |
| Vector DB | PostgreSQL 17 + pgvector 0.8.2 |
| Auth | JWT (HS256), bcrypt passwords, Fernet email encryption |
| MCP Server | FastMCP stdio — exposes DB + job-board tools to external agents |
| Frontend | React 19, Vite, TypeScript, Tailwind CSS v4, shadcn/ui |
| Testing | pytest, pytest-asyncio, httpx — 37 tests, no real DB/OpenAI calls |
| Infra | Docker Compose (Postgres), uv (Python deps) |

---

## Quick Start

### Prerequisites

- Docker Desktop
- Node.js 18+
- Python 3.13 (managed via `uv`)
- An OpenAI API key

### 1. Clone and configure

```bash
git clone <repo-url>
cd Capstone
cp backend/.env.example backend/.env   # then fill in your keys
```

**`backend/.env` required fields:**

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

DATABASE_URL=postgresql+asyncpg://hiring_user:hiring_pass@localhost:5432/hiring_db?ssl=disable

ENCRYPTION_KEY=<fernet-key>   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
JWT_SECRET_KEY=<random-string>
```

### 2. Start the database

```bash
docker compose up -d
```

### 3. Start the backend

```bash
cd /path/to/Capstone
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000
```

The server seeds two demo accounts on first startup — no manual DB setup needed.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev -- --port 3000
```

### 5. Open the app

| URL | What |
|-----|------|
| `http://localhost:3000` | HR/HM dashboard |
| `http://localhost:3000/jobs` | Public candidate job board |
| `http://localhost:8000/docs` | FastAPI Swagger UI |

---

## Demo Accounts

| Email | Password | Role |
|-------|----------|------|
| `hr@invictushiring.co` | `password` | HR (Sarah Chen) |
| `hm@invictushiring.co` | `password` | Hiring Manager (Alex Kumar) |

---

## Running Tests

```bash
cd /path/to/Capstone
.venv/bin/pytest -v
```

37 tests — all mocked, no real DB or OpenAI calls required.

---

## Optional Integrations

All job-board and email integrations are optional. The app runs fully without them — posting steps will show a graceful "not configured" status.

### Job boards (`backend/.env`)

```env
# LinkedIn
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_AUTHOR_URN=          # urn:li:person:ABC123 or urn:li:organization:12345

# Indeed
INDEED_PUBLISHER_ID=

# Google Jobs
GOOGLE_SERVICE_ACCOUNT_JSON=  # full JSON of a GCP service account key file
APP_BASE_URL=https://your-domain.com
```

### Email / SMTP (`backend/.env`)

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=hr@invictushiring.co
SMTP_USE_TLS=true
```

---

## Hiring Flow

```
1. HR/HM describes a role in plain English
2. Supervisor routes → JD Drafter generates a UK-compliant draft (RAG-assisted)
3. HR refines via chat, then approves or rejects with feedback
4. On approval → Job Publisher posts to LinkedIn / Indeed / Google Jobs
5. Candidates apply via the public job board (with optional CV upload)
6. CV Screener scores each application 0–100 in the background
7. HR shortlists strong candidates (star button in Applications panel)
8. Interview Scheduler generates a personalised invitation email + questions
9. HR edits and approves the email → sent via SMTP (or marked approved if unconfigured)
10. HR schedules the interview (date, format, location) → .ics download available
```

---

## Database Migrations

SQLAlchemy creates new tables automatically on startup. For columns added to existing tables, apply the migrations manually:

```bash
# Run once after pulling new schema changes
docker compose exec postgres psql -U hiring_user -d hiring_db \
  -f backend/migrations/002_candidate_cv_screening.sql

docker compose exec postgres psql -U hiring_user -d hiring_db \
  -f backend/migrations/003_interview_scheduling.sql
```

---

## MCP Server

Exposes hiring data and job-board tools to Claude Desktop or any MCP-compatible client:

```bash
PYTHONPATH=backend python backend/hiring_mcp/server.py
```

Available tools: `db_list_sessions`, `db_get_session`, `db_search_similar_jds`, `db_get_postings`, `linkedin_post_job`, `indeed_post_job`, `google_jobs_post_job`.

---

## Project Structure

```
Capstone/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, startup seeding
│   │   ├── core/                 # Config, DB engine, security, auth dependencies
│   │   ├── db/                   # SQLAlchemy models + shared query helpers
│   │   ├── services/             # AI agents (jd, cv_screener, interview, job_poster, analytics)
│   │   └── api/routes/           # REST endpoints (auth, jd, candidates, interviews, jobs, analytics)
│   ├── hiring_mcp/               # FastMCP stdio server
│   ├── migrations/               # SQL migration scripts
│   ├── tests/                    # pytest suite (37 tests)
│   └── .env                      # Local secrets — never commit
├── frontend/
│   └── src/
│       ├── api/                  # Typed fetch wrappers
│       ├── components/           # Dashboard, JD chat, Applications, Interview panels
│       ├── hooks/                # useJDSession state machine
│       ├── lib/                  # Shared utilities (downloadBlob)
│       └── pages/                # Public job board + job detail
├── Data/                         # Scripts for seeding past JDs into pgvector
├── docker-compose.yml            # PostgreSQL 17 + pgvector
└── pyproject.toml                # uv-managed Python dependencies
```