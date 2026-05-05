import asyncio
import json
import time
from typing import AsyncIterator

from loguru import logger
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.rag import retrieve_similar_jds
from app.services.agent_telemetry import fire_run
from sqlalchemy.ext.asyncio import AsyncSession

_client = AsyncOpenAI(api_key=settings.openai_api_key)

JD_PROMPT_VERSION = "jd-v1"

SYSTEM_PROMPT = """You are an expert HR copywriter specialising in UK job descriptions for InvictusHiring.
Your ONLY purpose is to draft, revise, and discuss job descriptions and HR-related content.

Guidelines:
- Use gender-neutral language throughout.
- Structure: Job Title → About the Company → The Role → Key Responsibilities →
  Required Skills → Nice-to-Have Skills → What We Offer (salary band) → Location & Work Arrangement.
- Keep responsibilities as bullet points (6–10 items).
- Required vs nice-to-have skills must be clearly separated.
- If information is missing, infer reasonable defaults but do not fabricate details.
- If past JDs are provided as context, adopt a similar tone and structure but do not copy verbatim.

STRICT SCOPE RULE: You only respond to questions and requests about job descriptions, hiring,
recruitment, HR policies, and the current draft. If a message is unrelated to these topics,
you MUST decline and redirect — do not attempt to answer it.
"""

_TOPIC_CHECK_SYSTEM = (
    "You are a strict topic classifier for a JD drafting assistant. "
    "Reply with exactly one word — 'yes' or 'no'. "
    "Reply 'yes' ONLY if the message is about: job descriptions, hiring, recruitment, HR, "
    "salary, skills, editing the current draft, job requirements, or work arrangements. "
    "Reply 'no' for EVERYTHING else, including general knowledge, coding, science, "
    "personal questions, or anything unrelated to HR and hiring."
)

_OFF_TOPIC_REPLY = (
    "I can only help with job description drafting and hiring-related queries. "
    "Please ask me something about the current JD — for example, adjusting the tone, "
    "adding responsibilities, or changing the salary band."
)


async def is_on_topic(message: str) -> bool:
    """Fast single-token classification: is this message hiring-related?"""
    response = await _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _TOPIC_CHECK_SYSTEM},
            {"role": "user", "content": message},
        ],
        max_tokens=1,
        temperature=0,
    )
    answer = response.choices[0].message.content.strip().lower()
    logger.debug(f"Topic check | message='{message[:60]}' result='{answer}'")
    return answer.startswith("y")

_EXTRACT_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_job_requirements",
        "description": "Extract structured job requirements from free-text input",
        "parameters": {
            "type": "object",
            "properties": {
                "title":               {"type": "string", "description": "Job title"},
                "department":          {"type": "string", "description": "Department or team"},
                "location":            {"type": "string", "description": "Office location or Remote"},
                "salary_band":         {"type": "string", "description": "Salary range, e.g. £60,000–£80,000"},
                "required_skills":     {"type": "array", "items": {"type": "string"}},
                "nice_to_have_skills": {"type": "array", "items": {"type": "string"}},
                "company_description": {"type": "string", "description": "Brief company description"},
            },
            "required": ["title", "required_skills"],
        },
    },
}


async def extract_requirements(text: str, session_id: str | None = None) -> dict:
    """Use OpenAI function calling to extract structured fields from free-text requirements."""
    logger.info(f"Extracting requirements from free text ({len(text)} chars)")
    t0 = time.perf_counter()
    status = "success"
    error_message = None
    try:
        response = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "Extract job requirements from the user's message. Infer missing fields where reasonable."},
                {"role": "user", "content": text},
            ],
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "function", "function": {"name": "extract_job_requirements"}},
            temperature=0,
        )
        args = response.choices[0].message.tool_calls[0].function.arguments
        extracted = json.loads(args)
        logger.info(f"Extracted requirements | title='{extracted.get('title')}' skills={extracted.get('required_skills')}")
    except Exception as exc:
        status = "error"
        error_message = str(exc)
        raise
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        asyncio.create_task(fire_run(
            agent_name="jd_drafter",
            operation="extract",
            prompt_version=JD_PROMPT_VERSION,
            model=settings.openai_model,
            status=status,
            latency_ms=latency_ms,
            session_id=session_id,
            input_tokens=response.usage.prompt_tokens if status == "success" else None,
            output_tokens=response.usage.completion_tokens if status == "success" else None,
            metrics={"input_chars": len(text), "fields_extracted": len(extracted) if status == "success" else 0},
            error_message=error_message,
        ))
    return extracted


def _build_initial_prompt(requirements: dict, past_jds: list[dict]) -> str:
    rag_context = ""
    if past_jds:
        rag_context = "\n\n## Reference JDs from our archive (for tone & structure only)\n"
        for i, jd in enumerate(past_jds, 1):
            rag_context += f"\n### Reference {i}: {jd['title']} ({jd['department']})\n{jd['content'][:1200]}\n"

    return f"""Please draft a Job Description based on the following requirements:

Job Title: {requirements.get('title', '')}
Department:{requirements.get('department', '')}
Location:{requirements.get('location', '')}
Salary Band: {requirements.get('salary_band', '')}
Required Skills:{', '.join(requirements.get('required_skills', []))}
Nice-to-Have Skills:{', '.join(requirements.get('nice_to_have_skills', []))}
Company Description:{requirements.get('company_description', '')}
{f"Additional Context: {requirements.get('additional_context')}" if requirements.get('additional_context') else ""}
{rag_context}

Draft the full JD now."""


async def stream_initial_draft(requirements: dict, db: AsyncSession, session_id: str | None = None) -> AsyncIterator[str]:
    """Stream the first JD draft using RAG context from past JDs."""
    logger.info(f"Drafting JD | title='{requirements.get('title')}' location='{requirements.get('location')}'")
    query = f"{requirements.get('title', '')} {requirements.get('department', '')} {' '.join(requirements.get('required_skills', []))}"
    past_jds = await retrieve_similar_jds(query, db)

    user_prompt = _build_initial_prompt(requirements, past_jds)

    logger.debug(f"Calling OpenAI for initial draft | model={settings.openai_model} rag_hits={len(past_jds)}")
    t0 = time.perf_counter()
    output_chars = 0
    input_tokens = output_tokens = None
    status = "success"
    error_message = None

    try:
        stream = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
            stream_options={"include_usage": True},
            temperature=0.4,
        )

        async for chunk in stream:
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
                continue
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                output_chars += len(delta)
                yield delta

    except Exception as exc:
        status = "error"
        error_message = str(exc)
        raise
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(f"Initial draft complete | chars={output_chars} latency={latency_ms}ms")
        asyncio.create_task(fire_run(
            agent_name="jd_drafter",
            operation="initial_draft",
            prompt_version=JD_PROMPT_VERSION,
            model=settings.openai_model,
            status=status,
            latency_ms=latency_ms,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metrics={"rag_hits": len(past_jds), "output_chars": output_chars},
            error_message=error_message,
        ))


async def stream_revision(
    feedback: str,
    current_draft: str,
    history: list[dict],
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream a revised JD draft given rejection feedback and chat history."""
    logger.info(f"Revising JD | feedback='{feedback[:80]}…' history_len={len(history)}")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": f"The following feedback was provided on the draft:\n\n{feedback}\n\n"
                   f"Current draft:\n\n{current_draft}\n\nPlease revise the JD accordingly.",
    })

    t0 = time.perf_counter()
    output_chars = 0
    input_tokens = output_tokens = None
    status = "success"
    error_message = None

    try:
        stream = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            temperature=0.4,
        )

        async for chunk in stream:
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
                continue
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                output_chars += len(delta)
                yield delta

    except Exception as exc:
        status = "error"
        error_message = str(exc)
        raise
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(f"Revision complete | chars={output_chars} latency={latency_ms}ms")
        asyncio.create_task(fire_run(
            agent_name="jd_drafter",
            operation="revision",
            prompt_version=JD_PROMPT_VERSION,
            model=settings.openai_model,
            status=status,
            latency_ms=latency_ms,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metrics={"feedback_chars": len(feedback), "output_chars": output_chars, "history_turns": len(history)},
            error_message=error_message,
        ))


async def stream_chat_reply(
    user_message: str,
    current_draft: str,
    history: list[dict],
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream a response to a free-form chat message about the JD."""
    logger.info(f"Chat reply | message='{user_message[:80]}' history_len={len(history)}")

    on_topic = await is_on_topic(user_message)
    if not on_topic:
        logger.info(f"Off-topic message blocked | message='{user_message[:80]}'")
        asyncio.create_task(fire_run(
            agent_name="jd_drafter",
            operation="chat",
            prompt_version=JD_PROMPT_VERSION,
            model=settings.openai_model,
            status="success",
            latency_ms=0,
            session_id=session_id,
            metrics={"on_topic": False, "blocked": True},
        ))
        yield _OFF_TOPIC_REPLY
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": f"Current JD draft:\n\n{current_draft}\n\nUser message: {user_message}",
    })

    t0 = time.perf_counter()
    output_chars = 0
    input_tokens = output_tokens = None
    status = "success"
    error_message = None

    try:
        stream = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            temperature=0.4,
        )

        async for chunk in stream:
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
                continue
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                output_chars += len(delta)
                yield delta

    except Exception as exc:
        status = "error"
        error_message = str(exc)
        raise
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(f"Chat reply complete | chars={output_chars} latency={latency_ms}ms")
        asyncio.create_task(fire_run(
            agent_name="jd_drafter",
            operation="chat",
            prompt_version=JD_PROMPT_VERSION,
            model=settings.openai_model,
            status=status,
            latency_ms=latency_ms,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metrics={"on_topic": True, "output_chars": output_chars, "history_turns": len(history)},
            error_message=error_message,
        ))