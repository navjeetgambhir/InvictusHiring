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
            "id": "jd.chat",
            "name": "Refine draft via chat",
            "description": (
                "Free-form follow-up conversation to adjust tone, add requirements, "
                "or restructure sections of an existing draft."
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
                "rejection triggers an automatic revision stream."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["text/markdown"],
            "endpoint": "POST /api/jd/approve",
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
        "saving each posting record to the database."
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
                "for LinkedIn, Indeed UK, and Google Jobs in parallel, and streams "
                "NDJSON events: {type: start}, {type: posted, url, content}, {type: done}."
            ),
            "inputModes": ["application/json"],
            "outputModes": ["application/x-ndjson"],
            "endpoint": "POST /api/jobs/post/{session_id}",
            "targetPlatforms": ["linkedin", "indeed", "google_jobs"],
        },
        {
            "id": "jobs.list-postings",
            "name": "List postings for a session",
            "description": "Returns all platform posting records for a given JD session.",
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
            "endpoint": "GET /api/jobs/postings/{session_id}",
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


@router.get("/.well-known/agents", tags=["Agent Registry"])
async def list_agents():
    """Agent registry — returns the well-known card URL for every hosted agent."""
    return {
        "agents": [
            {
                "id": "jd-drafter",
                "name": _JD_DRAFTER_CARD["name"],
                "cardUrl": "http://localhost:8000/.well-known/jd-drafter/agent-card.json",
            },
            {
                "id": "job-poster",
                "name": _JOB_POSTER_CARD["name"],
                "cardUrl": "http://localhost:8000/.well-known/job-poster/agent-card.json",
            },
        ]
    }
