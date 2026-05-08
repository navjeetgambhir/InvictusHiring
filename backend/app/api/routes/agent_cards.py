"""
A2A-compliant AgentCard endpoints.

Each agent exposes its card at /.well-known/<agent>/agent-card.json
following the Agent-to-Agent (A2A) protocol specification.

Clients can discover capabilities via a simple HTTP GET — no auth required.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# ── Shared provider block ─────────────────────────────────────────────────────

_PROVIDER = {
    "organization": "InvictusHiring",
    "url": "http://localhost:8000",
}

# ── Agent 1 — JD Drafter ──────────────────────────────────────────────────────

_JD_DRAFTER_CARD = {
    "schemaVersion": "1.0",
    "name": "JD Drafter",
    "description": (
        "Conversational AI agent that turns plain-English hiring briefs into "
        "structured, UK-compliant job descriptions. Uses OpenAI function-calling "
        "to extract requirements, retrieves similar past JDs via pgvector RAG, "
        "then streams a full draft for human review and iterative refinement."
    ),
    "url": "http://localhost:8000/api/jd",
    "version": "1.0.0",
    "provider": _PROVIDER,
    "documentationUrl": "http://localhost:8000/docs#/jd",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "stateTransitionHistory": True,
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain", "text/markdown"],
    "skills": [
        {
            "id": "jd.draft-freetext",
            "name": "Draft from free text",
            "description": (
                "Accepts a plain-English hiring brief, extracts structured fields "
                "(title, department, location, salary, required/nice-to-have skills) "
                "via function calling, and streams a full JD draft."
            ),
            "inputModes": ["text/plain"],
            "outputModes": ["text/markdown"],
            "endpoint": "POST /api/jd/draft-freetext",
        },
        {
            "id": "jd.draft-structured",
            "name": "Draft from structured form",
            "description": (
                "Accepts a pre-structured requirements object and streams a full JD draft "
                "without the extraction step."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["text/markdown"],
            "endpoint": "POST /api/jd/draft",
        },
        {
            "id": "jd.chat",
            "name": "Refine draft via chat",
            "description": (
                "Free-form follow-up conversation to adjust tone, add requirements, "
                "or restructure sections of an existing draft. Off-topic messages "
                "are blocked before reaching OpenAI."
            ),
            "inputModes": ["text/plain"],
            "outputModes": ["text/markdown"],
            "endpoint": "POST /api/jd/chat",
        },
        {
            "id": "jd.approve",
            "name": "Approve or reject with feedback",
            "description": (
                "Marks a draft approved (ready for publishing) or rejected; "
                "rejection triggers an automatic revision stream with the provided feedback."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["text/markdown"],
            "endpoint": "POST /api/jd/approve",
        },
        {
            "id": "jd.sessions",
            "name": "List sessions",
            "description": (
                "Returns all JD drafting sessions for the authenticated user, "
                "newest first, with status and last message preview."
            ),
            "inputModes": [],
            "outputModes": ["application/json"],
            "endpoint": "GET /api/jd/sessions",
        },
        {
            "id": "jd.session-detail",
            "name": "Get session detail",
            "description": (
                "Returns the full session state, latest draft content, and complete "
                "chat history for a given session."
            ),
            "inputModes": [],
            "outputModes": ["application/json"],
            "endpoint": "GET /api/jd/session/{session_id}",
        },
        {
            "id": "jd.rag-retrieval",
            "name": "RAG retrieval from past JDs",
            "description": (
                "Internally embeds requirements with text-embedding-3-small and "
                "retrieves the top-K most similar historical JDs from pgvector "
                "to ground new drafts in company style and structure."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "endpoint": "internal",
        },
    ],
}

# ── Agent 2 — Job Poster ──────────────────────────────────────────────────────

_JOB_POSTER_CARD = {
    "schemaVersion": "1.0",
    "name": "Job Poster",
    "description": (
        "Downstream AI agent that takes an approved JD and reformats it for "
        "each job board's specific tone, character limits, and structure. "
        "Streams per-platform progress (start → formatted → posted) as NDJSON, "
        "saving each posting record to the database. Falls back gracefully if "
        "platform credentials are not configured."
    ),
    "url": "http://localhost:8000/api/jobs",
    "version": "1.0.0",
    "provider": _PROVIDER,
    "documentationUrl": "http://localhost:8000/docs#/jobs",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "stateTransitionHistory": True,
    },
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/x-ndjson"],
    "skills": [
        {
            "id": "jobs.post",
            "name": "Post JD to job boards",
            "description": (
                "Accepts a session_id for an approved JD, reformats the content "
                "for LinkedIn, Indeed UK, and Google Jobs using OpenAI, and streams "
                "NDJSON events: {type: start}, {type: chunk}, {type: posted, url, content}, {type: done}."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["application/x-ndjson"],
            "endpoint": "POST /api/jobs/post/{session_id}",
            "targetPlatforms": ["linkedin", "indeed", "google_jobs"],
        },
        {
            "id": "jobs.list-postings",
            "name": "List postings for a session",
            "description": "Returns all platform posting records and their status for a given JD session.",
            "inputModes": [],
            "outputModes": ["application/json"],
            "endpoint": "GET /api/jobs/postings/{session_id}",
        },
        {
            "id": "jobs.indeed-feed",
            "name": "Indeed XML feed",
            "description": (
                "Serves an Indeed-compatible XML job feed for a published session. "
                "Crawled by Indeed to ingest job listings."
            ),
            "inputModes": [],
            "outputModes": ["application/xml"],
            "endpoint": "GET /api/jobs/indeed-feed/{session_id}.xml",
        },
        {
            "id": "jobs.google-jobs-page",
            "name": "Google Jobs HTML page",
            "description": (
                "Serves a schema.org/JobPosting JSON-LD HTML page for a published session. "
                "Submitted to Google Indexing API for fast crawl."
            ),
            "inputModes": [],
            "outputModes": ["text/html"],
            "endpoint": "GET /api/jobs/jobs/{session_id}",
        },
    ],
}

# ── Agent 3 — CV Screener ─────────────────────────────────────────────────────

_CV_SCREENER_CARD = {
    "schemaVersion": "1.0",
    "name": "CV Screener",
    "description": (
        "AI-powered candidate screening agent that runs as a background task "
        "immediately after a candidate submits an application. Extracts text from "
        "PDF, DOCX, or TXT CVs, scores the candidate 0–100 against the job "
        "requirements, and writes structured results (score, summary, strengths, "
        "gaps, recommendation) back to the database."
    ),
    "url": "http://localhost:8000/api/candidates",
    "version": "1.0.0",
    "provider": _PROVIDER,
    "documentationUrl": "http://localhost:8000/docs#/candidates",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "defaultInputModes": ["multipart/form-data"],
    "defaultOutputModes": ["application/json"],
    "skills": [
        {
            "id": "candidates.apply",
            "name": "Submit application",
            "description": (
                "Public endpoint — accepts candidate name, email, optional phone, "
                "optional CV file (PDF/DOCX/TXT, max 5 MB), and optional cover letter. "
                "Saves the application and triggers background CV screening."
            ),
            "inputModes": ["multipart/form-data"],
            "outputModes": ["application/json"],
            "endpoint": "POST /api/candidates/apply/{session_id}",
            "auth": "none",
        },
        {
            "id": "candidates.screen-cv",
            "name": "AI CV screening",
            "description": (
                "Internal background task: extracts text from the uploaded CV, "
                "calls OpenAI to produce a 0–100 score, recommendation "
                "(strong_match | good_match | partial_match | poor_match), "
                "strengths list, gaps list, and a 2–3 sentence summary."
            ),
            "inputModes": ["application/octet-stream"],
            "outputModes": ["application/json"],
            "endpoint": "internal",
        },
        {
            "id": "candidates.list-applications",
            "name": "List applications for a session",
            "description": (
                "HR/HM only — returns all applications for a JD session with "
                "AI screening scores, recommendation, strengths, gaps, and shortlist status."
            ),
            "inputModes": [],
            "outputModes": ["application/json"],
            "endpoint": "GET /api/candidates/applications/{session_id}",
            "auth": "jwt",
        },
        {
            "id": "candidates.download-cv",
            "name": "Download candidate CV",
            "description": "HR/HM only — streams the uploaded CV file for a given application.",
            "inputModes": [],
            "outputModes": ["application/octet-stream"],
            "endpoint": "GET /api/candidates/applications/{session_id}/cv/{application_id}",
            "auth": "jwt",
        },
        {
            "id": "candidates.toggle-shortlist",
            "name": "Toggle shortlist",
            "description": "HR/HM only — adds or removes a candidate from the shortlist.",
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "endpoint": "POST /api/candidates/applications/{application_id}/shortlist",
            "auth": "jwt",
        },
        {
            "id": "candidates.job-board",
            "name": "Public job board",
            "description": "Returns all published JDs for the public candidate job board.",
            "inputModes": [],
            "outputModes": ["application/json"],
            "endpoint": "GET /api/candidates/jobs",
            "auth": "none",
        },
    ],
}

# ── Agent 4 — Analytics (NLP→SQL) ────────────────────────────────────────────

_ANALYTICS_CARD = {
    "schemaVersion": "1.0",
    "name": "Analytics Agent",
    "description": (
        "NLP-to-SQL agent that answers natural language questions about hiring data. "
        "Generates a safe, read-only SELECT query from the user's question via OpenAI, "
        "validates it with an AST parser (no INSERT/UPDATE/DELETE/DDL permitted), "
        "executes it against PostgreSQL, and streams a natural language answer as NDJSON."
    ),
    "url": "http://localhost:8000/api/analytics",
    "version": "1.0.0",
    "provider": _PROVIDER,
    "documentationUrl": "http://localhost:8000/docs#/analytics",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["application/x-ndjson"],
    "skills": [
        {
            "id": "analytics.query",
            "name": "NLP to SQL query",
            "description": (
                "Accepts a plain-English question about hiring data "
                "(e.g. 'How many applications did we receive this week?', "
                "'Which roles have the most strong_match candidates?'). "
                "Streams NDJSON: {type: sql, sql: '...'}, {type: chunk, text: '...'}, {type: done}."
            ),
            "inputModes": ["text/plain"],
            "outputModes": ["application/x-ndjson"],
            "endpoint": "POST /api/analytics/query",
            "auth": "jwt",
        },
        {
            "id": "analytics.route",
            "name": "Supervisor routing",
            "description": (
                "Context-aware message router. Given a user message, current pipeline_state, "
                "has_draft flag, and recent history, returns a RoutingDecision: "
                "intent (jd_draft | jd_chat | jd_revise | approve | publish | analytics | other), "
                "confidence (0–1), reasoning, and suggested_action."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "endpoint": "POST /api/analytics/route",
            "auth": "jwt",
        },
    ],
}

# ── Agent 5 — Interview Scheduler ────────────────────────────────────────────

_INTERVIEW_SCHEDULER_CARD = {
    "schemaVersion": "1.0",
    "name": "Interview Scheduler",
    "description": (
        "AI agent that automates interview scheduling for shortlisted candidates. "
        "Generates personalised, AI-drafted interview invitation emails and "
        "coordinates scheduling with candidates."
    ),
    "url": "http://localhost:8000/api/interviews",
    "version": "1.0.0",
    "provider": _PROVIDER,
    "documentationUrl": "http://localhost:8000/docs#/interviews",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": True,
    },
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json"],
    "skills": [
        {
            "id": "interviews.schedule",
            "name": "Schedule interview",
            "description": (
                "Accepts a shortlisted application_id and interview slot details, "
                "generates an AI-drafted invitation email, and records the scheduled interview."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "endpoint": "POST /api/interviews/schedule",
            "auth": "jwt",
        },
        {
            "id": "interviews.list",
            "name": "List scheduled interviews",
            "description": "Returns all scheduled interviews for a given JD session.",
            "inputModes": [],
            "outputModes": ["application/json"],
            "endpoint": "GET /api/interviews/{session_id}",
            "auth": "jwt",
        },
    ],
}

# ── Agent 6 — ML Predictor ───────────────────────────────────────────────────

_ML_PREDICTOR_CARD = {
    "schemaVersion": "1.0",
    "name": "ML Predictor",
    "description": (
        "Agent 6 — natural language interface to the trained fit and join-prediction ML models. "
        "Accepts plain-English questions about candidate fit or offer acceptance probability, "
        "runs scikit-learn GradientBoosting predictions against all matching candidates, "
        "and streams a structured result set plus a natural language summary."
    ),
    "url": "http://localhost:8000/api/ml",
    "version": "1.0.0",
    "provider": _PROVIDER,
    "documentationUrl": "http://localhost:8000/docs#/ML%20Predictions",
    "capabilities": {
        "streaming": True,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/x-ndjson"],
    "skills": [
        {
            "id": "ml.predict",
            "name": "Fit and join prediction query",
            "description": (
                "Accepts a plain-English question and an optional session_id filter. "
                "Parses the intent (fit | join | both), fetches matching applications from "
                "the DB, runs the trained GradientBoosting models, and streams NDJSON: "
                "{type: results, data: [...]}, {type: chunk, text: '...'}, {type: done}. "
                "Returns null scores with a warning when models have not been trained yet."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["application/x-ndjson"],
            "endpoint": "POST /api/ml/predict",
            "auth": "jwt",
            "exampleQuestions": [
                "What is the fit score for all candidates in this role?",
                "Which shortlisted candidates are most likely to accept an offer?",
                "Rank candidates by join probability for session <uuid>",
                "Show me fit and join scores for Alice Johnson",
            ],
        },
    ],
}

# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/.well-known/jd-drafter/agent-card.json", include_in_schema=False)
async def jd_drafter_agent_card():
    return JSONResponse(_JD_DRAFTER_CARD, media_type="application/json")


@router.get("/.well-known/job-poster/agent-card.json", include_in_schema=False)
async def job_poster_agent_card():
    return JSONResponse(_JOB_POSTER_CARD, media_type="application/json")


@router.get("/.well-known/cv-screener/agent-card.json", include_in_schema=False)
async def cv_screener_agent_card():
    return JSONResponse(_CV_SCREENER_CARD, media_type="application/json")


@router.get("/.well-known/analytics/agent-card.json", include_in_schema=False)
async def analytics_agent_card():
    return JSONResponse(_ANALYTICS_CARD, media_type="application/json")


@router.get("/.well-known/interview-scheduler/agent-card.json", include_in_schema=False)
async def interview_scheduler_agent_card():
    return JSONResponse(_INTERVIEW_SCHEDULER_CARD, media_type="application/json")


@router.get("/.well-known/ml-predictor/agent-card.json", include_in_schema=False)
async def ml_predictor_agent_card():
    return JSONResponse(_ML_PREDICTOR_CARD, media_type="application/json")


@router.get("/.well-known/agents", tags=["Agent Registry"])
async def list_agents():
    """Agent registry — returns the well-known card URL for every hosted agent."""
    return {
        "agents": [
            {
                "id": "jd-drafter",
                "name": _JD_DRAFTER_CARD["name"],
                "description": "Draft UK-compliant job descriptions from plain English.",
                "cardUrl": "http://localhost:8000/.well-known/jd-drafter/agent-card.json",
            },
            {
                "id": "job-poster",
                "name": _JOB_POSTER_CARD["name"],
                "description": "Reformat and publish approved JDs to LinkedIn, Indeed UK, and Google Jobs.",
                "cardUrl": "http://localhost:8000/.well-known/job-poster/agent-card.json",
            },
            {
                "id": "cv-screener",
                "name": _CV_SCREENER_CARD["name"],
                "description": "Score candidates 0–100 against job requirements from uploaded CVs.",
                "cardUrl": "http://localhost:8000/.well-known/cv-screener/agent-card.json",
            },
            {
                "id": "analytics",
                "name": _ANALYTICS_CARD["name"],
                "description": "Answer plain-English questions about hiring data via NLP-to-SQL.",
                "cardUrl": "http://localhost:8000/.well-known/analytics/agent-card.json",
            },
            {
                "id": "interview-scheduler",
                "name": _INTERVIEW_SCHEDULER_CARD["name"],
                "description": "Schedule interviews and generate AI-drafted invitation emails.",
                "cardUrl": "http://localhost:8000/.well-known/interview-scheduler/agent-card.json",
            },
            {
                "id": "ml-predictor",
                "name": _ML_PREDICTOR_CARD["name"],
                "description": "Natural language queries for ML-predicted candidate fit and offer acceptance.",
                "cardUrl": "http://localhost:8000/.well-known/ml-predictor/agent-card.json",
            },
        ]
    }