"""
Supervisor — context-aware orchestration layer for the Invictus Hiring agent pipeline.

This is the single place that describes WHAT each agent does and WHEN it runs.
All routes import from here instead of calling agent files directly.

Self-adapting routing
─────────────────────
The supervisor reads THREE inputs before deciding how to route a message:
  1. The message itself
  2. The current pipeline state (idle / drafting / pending_approval / approved / published)
  3. Recent conversation history

This means the same words mean different things in different states:

  Message: "looks good"
    + state=pending_approval  → intent: approve
    + state=idle              → intent: other (greeting)

  Message: "add a remote-first clause"
    + state=pending_approval  → intent: jd_chat (refine the draft)
    + state=idle              → intent: jd_draft (start a new JD)

  Message: "how many applied?"
    + state=published         → intent: analytics (query applications)
    + state=idle              → intent: analytics (general query)

  Message: "publish this"
    + state=approved          → intent: publish
    + state=idle              → intent: other (nothing to publish)

RoutingDecision fields
──────────────────────
  intent          — primary action to take (see INTENT VALUES below)
  confidence      — 0.0–1.0; below 0.5 the route falls back to "other"
  reasoning       — one sentence explaining the decision (logged + returned to UI)
  suggested_action — plain English hint for the UI / downstream agent
  secondary_intent — optional second action if the message has two parts

INTENT VALUES
─────────────
  jd_draft    → Agent 1: start a brand-new JD from scratch
  jd_chat     → Agent 1: refine / chat about the current draft
  jd_revise   → Agent 1: reject + revise the current draft with feedback
  approve     → mark the current draft as approved (no agent call needed)
  publish     → Agent 2: post the approved JD to job boards
  analytics   → Agent 4: NLP→SQL data question
  other       → off-topic / greeting / no action

Pipeline overview
─────────────────

  [User / HR / HM message + session state + history]
          │
          ▼
  ┌──────────────────────────────────────────────┐
  │  supervisor_route()                          │
  │  Context-aware JSON routing decision         │
  │  intent · confidence · reasoning · action    │
  └──────┬──────────────┬───────────────┬────────┘
         │              │               │
         ▼              ▼               ▼
  [Agent 1]       [Agent 2]       [Agent 4]
  JD Drafter      Job Poster      NLP→SQL
  jd_agent.py     job_poster_     analytics_
                  agent.py        agent.py
         │
         │  Candidate applies
         ▼
  [Agent 3 — CV Screener]   cv_screener.py
  BackgroundTask on apply

JD state machine
────────────────
drafting → pending_approval → approved → publishing → published
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.jd_agent import (
    extract_requirements,
    stream_initial_draft,
    stream_chat_reply,
    stream_revision,
)
from app.services.job_poster_agent import stream_job_postings
from app.services.cv_screener import run_screening
from app.services.analytics_agent import stream_analytics_response
from app.services.agent_telemetry import fire_run

_client = AsyncOpenAI(api_key=settings.openai_api_key)

SUPERVISOR_PROMPT_VERSION = "supervisor-v1"

# ── Routing decision ──────────────────────────────────────────────────────────

VALID_INTENTS = {"jd_draft", "jd_chat", "jd_revise", "approve", "publish", "analytics", "other"}

@dataclass
class RoutingDecision:
    intent: str           # primary action
    confidence: float     # 0.0–1.0
    reasoning: str        # one sentence explanation
    suggested_action: str # plain English hint for the caller
    secondary_intent: str | None = None  # set when message has two parts


# ── Context-aware supervisor ──────────────────────────────────────────────────

_ROUTE_SYSTEM = """You are the supervisor for an AI-powered HR hiring platform.
Your job is to decide how to route a user message to the right agent.

You must return a JSON object with exactly these fields:
{
  "intent": "<one of: jd_draft | jd_chat | jd_revise | approve | publish | analytics | other>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<one sentence explaining why>",
  "suggested_action": "<plain English hint for the downstream agent or UI>",
  "secondary_intent": "<optional second intent if message clearly has two parts, else null>"
}

INTENT DEFINITIONS — read carefully, they are state-dependent:

  jd_draft    Start a brand-new job description from scratch.
              Use when: state is idle AND message describes a new role.

  jd_chat     Refine or discuss the current draft conversationally.
              Use when: a draft already exists AND the message is about editing, tone, content, or wording.

  jd_revise   Reject the current draft and request a formal revision with feedback.
              Use when: state is pending_approval AND message expresses clear dissatisfaction or specific revision requests.

  approve     The user is happy with the current draft and wants to approve it.
              Use when: state is pending_approval AND message signals approval ("looks good", "approve", "perfect", "that's great", "go ahead").

  publish     Post the approved JD to job boards.
              Use when: state is approved AND message requests posting/publishing.

  analytics   A data question about applications, candidates, JD statuses, counts, or reports.
              Always valid regardless of state.

  other       Greetings, thanks, off-topic, or unclear.

ADAPTATION RULES:
- The SAME message routes differently depending on pipeline_state.
- "looks good" + pending_approval → approve (high confidence)
- "looks good" + idle → other (no draft exists)
- "add remote work" + pending_approval → jd_chat (refine existing draft)
- "add remote work" + idle → jd_draft (start new JD with remote work requirement)
- "publish this" + approved → publish
- "publish this" + idle → other (nothing approved yet)
- Short affirmatives during pending_approval always mean approve unless they include edit instructions.
- If confidence < 0.5, default intent to "other".
"""


async def supervisor_route(
    message: str,
    pipeline_state: str,
    history: list[dict] | None = None,
    has_draft: bool = False,
) -> RoutingDecision:
    """
    Context-aware routing decision.

    Args:
        message:        The user's raw message.
        pipeline_state: Current JD state — idle | drafting | pending_approval |
                        approved | publishing | published.
        history:        Last few chat messages for context (optional, capped at 6).
        has_draft:      Whether a JD draft currently exists in this session.

    Returns:
        RoutingDecision with intent, confidence, reasoning, suggested_action.
    """
    context_block = (
        f"pipeline_state: {pipeline_state}\n"
        f"has_draft: {has_draft}\n"
    )
    if history:
        recent = history[-6:]
        context_block += "recent_history:\n" + "\n".join(
            f"  [{m['role']}]: {m['content'][:120]}" for m in recent
        )

    from openai.types.chat import ChatCompletionMessageParam
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _ROUTE_SYSTEM},
        {"role": "user", "content": f"CONTEXT:\n{context_block}\n\nMESSAGE: {message}"},
    ]

    t0 = time.perf_counter()
    status = "success"
    error_message = None
    input_tokens = output_tokens = None

    try:
        response = await _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content or "{}")
        intent = raw.get("intent", "other").lower().strip()
        if intent not in VALID_INTENTS:
            intent = "other"
        confidence = float(raw.get("confidence", 0.5))
        if confidence < 0.5:
            intent = "other"
        decision = RoutingDecision(
            intent=intent,
            confidence=confidence,
            reasoning=raw.get("reasoning", ""),
            suggested_action=raw.get("suggested_action", ""),
            secondary_intent=raw.get("secondary_intent") or None,
        )
        if response.usage:
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
    except Exception as exc:
        logger.error(f"Supervisor routing failed: {exc} — falling back to 'other'")
        status = "error"
        error_message = str(exc)
        decision = RoutingDecision(
            intent="other",
            confidence=0.0,
            reasoning="Routing error — fallback applied.",
            suggested_action="Ask the user to rephrase.",
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        f"Supervisor | route | intent={decision.intent} "
        f"confidence={decision.confidence:.2f} "
        f"state={pipeline_state} | {decision.reasoning} | {latency_ms}ms"
    )
    asyncio.create_task(fire_run(
        agent_name="supervisor",
        operation="route",
        prompt_version=SUPERVISOR_PROMPT_VERSION,
        model="gpt-4o-mini",
        status=status,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        metrics={
            "intent": decision.intent,
            "confidence": decision.confidence,
            "pipeline_state": pipeline_state,
            "has_draft": has_draft,
            "routing_fallback": status == "error",
            "secondary_intent": decision.secondary_intent,
        },
        error_message=error_message,
    ))
    return decision


# Keep the old simple classify_intent for backward-compat with the /analytics/classify route
async def supervisor_classify(message: str) -> str:
    """
    Simple single-intent classifier for the /analytics/classify endpoint.
    For richer routing use supervisor_route() instead.
    """
    decision = await supervisor_route(message, pipeline_state="idle")
    # Map the richer intents back to the three-value API contract
    if decision.intent in ("jd_draft", "jd_chat", "jd_revise"):
        return "jd_draft"
    if decision.intent == "analytics":
        return "analytics"
    return "other"


# ── Agent 1: JD Drafter ───────────────────────────────────────────────────────

async def agent1_extract(free_text: str, session_id: str | None = None) -> dict:
    """
    Step 1a (freetext path only).
    Calls OpenAI function calling to pull structured fields out of plain English:
    title, department, location, salary_band, required_skills, nice_to_have_skills.
    """
    logger.info("Supervisor | Agent 1 — extracting requirements from free text")
    return await extract_requirements(free_text, session_id=session_id)


def agent1_draft(requirements: dict, db: AsyncSession, session_id: str | None = None) -> AsyncIterator[str]:
    """
    Step 1b — first draft (both freetext and structured paths).
    Builds a pgvector RAG query from the requirements, retrieves similar past JDs,
    injects them as context, then streams the OpenAI response chunk by chunk.
    Call AFTER flushing the JDRequest to the DB so the session_id exists.
    """
    logger.info(f"Supervisor | Agent 1 — drafting | title='{requirements.get('title')}'")
    return stream_initial_draft(requirements, db, session_id=session_id)


def agent1_chat(
    user_message: str,
    current_draft: str,
    history: list[dict],
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Conversational refinement of the current draft.
    Off-topic messages are blocked inside stream_chat_reply before hitting OpenAI.
    """
    logger.info("Supervisor | Agent 1 — chat refinement")
    return stream_chat_reply(user_message, current_draft, history, session_id=session_id)


def agent1_revise(
    feedback: str,
    current_draft: str,
    history: list[dict],
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Auto-revision triggered when HR rejects with written feedback.
    Streams a new draft version; the route bumps draft.version and saves it.
    """
    logger.info(f"Supervisor | Agent 1 — revision | feedback='{feedback[:60]}…'")
    return stream_revision(feedback, current_draft, history, session_id=session_id)


# ── Agent 2: Job Poster ───────────────────────────────────────────────────────

def agent2_publish(
    jd_content: str,
    title: str,
    session_id: str,
) -> AsyncGenerator[str, None]:
    """
    Triggered after HR approves the JD (status == 'approved').
    Reformats the draft for each platform via OpenAI, then publishes.
    Falls back gracefully if platform credentials are not configured.

    Streams NDJSON lines so the UI can show per-platform progress:
      {"type": "start",  "platform": "LinkedIn"}
      {"type": "chunk",  "platform": "LinkedIn", "text": "..."}
      {"type": "posted", "platform": "LinkedIn", "url": "...", "content": "..."}
      {"type": "error",  "platform": "LinkedIn", "message": "..."}
      {"type": "done"}
    """
    logger.info(f"Supervisor | Agent 2 — publish | title='{title}' session={session_id}")
    return stream_job_postings(jd_content, title, session_id)


# ── Agent 3: CV Screener ──────────────────────────────────────────────────────

async def agent3_screen(application_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Runs as a FastAPI BackgroundTask right after a candidate submits their application.

    1. Reads the saved CV file from cv_uploads/
    2. Extracts plain text (pypdf for PDF, python-docx for DOCX, utf-8 for TXT)
    3. Calls OpenAI to score the candidate 0–100 against the job requirements
    4. Writes results back to CandidateApplication:
         screening_status, screening_score, screening_summary,
         screening_strengths, screening_gaps, screening_recommendation
    """
    logger.info(f"Supervisor | Agent 3 — CV screening | application_id={application_id}")
    await run_screening(application_id, db)


# ── Agent 4: NLP→SQL Analytics ────────────────────────────────────────────────

def agent4_query(question: str, db: AsyncSession) -> AsyncIterator[str]:
    """
    Answers natural language questions about hiring data by:
      1. Generating a safe read-only SELECT query from the question (OpenAI)
      2. Executing it against the Postgres DB
      3. Streaming a natural language answer back as NDJSON

    Only SELECT queries are permitted — INSERT/UPDATE/DELETE/DDL are blocked.
    Streams NDJSON lines:
      {"type": "sql",   "sql": "SELECT ..."}
      {"type": "chunk", "text": "..."}
      {"type": "done"}
      {"type": "error", "message": "..."}

    Example questions:
      "How many applications did we receive this week?"
      "Which roles have the most strong_match candidates?"
      "Show me all published JDs in the Engineering department."
    """
    logger.info(f"Supervisor | Agent 4 — NLP→SQL | question='{question[:80]}'")
    return stream_analytics_response(question, db)