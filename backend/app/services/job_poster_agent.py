"""
Job Poster Agent — Agent 2.

Takes an approved JD, reformats it for each job platform using OpenAI streaming,
then publishes to the real platform API.  Falls back gracefully if credentials
are not configured so the demo still works without API keys.

Stream protocol (one JSON object per line):
  {"type": "start",  "platform": "LinkedIn"}
  {"type": "chunk",  "platform": "LinkedIn", "text": "..."}
  {"type": "posted", "platform": "LinkedIn", "platform_id": "linkedin", "url": "...", "content": "..."}
  {"type": "error",  "platform": "LinkedIn", "message": "..."}
  {"type": "done"}
"""

import json
from typing import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI

from app.core.config import settings
from app.services.platforms.linkedin import post_to_linkedin
from app.services.platforms.indeed import post_to_indeed
from app.services.platforms.google_jobs import post_to_google_jobs

_client = AsyncOpenAI(api_key=settings.openai_api_key)

POSTER_PROMPT_VERSION = "poster-v1"

_PLATFORMS = [
    {
        "id": "linkedin",
        "name": "LinkedIn",
        "instructions": (
            "Reformat the following job description for a LinkedIn Jobs post. "
            "LinkedIn audiences respond to professional yet engaging copy. "
            "Structure it with these sections: a 2-sentence role overview, "
            "About the Role, Key Responsibilities (bullets), What You'll Bring (bullets), "
            "Nice to Have (bullets), What We Offer (bullets). "
            "Keep the tone warm and forward-looking. Do not exceed 800 words."
        ),
    },
    {
        "id": "indeed",
        "name": "Indeed UK",
        "instructions": (
            "Reformat the following job description for an Indeed UK posting. "
            "Indeed UK readers skim quickly — use short bullet points throughout, "
            "surface the salary band and location in the first paragraph, "
            "and use UK English (e.g. 'organisation', 'colour', 'programme'). "
            "Sections: Summary, The Role, Responsibilities, Requirements, Desirable, Package. "
            "Keep it under 600 words and comply with UK employment-law terminology."
        ),
    },
    {
        "id": "google_jobs",
        "name": "Google Jobs",
        "instructions": (
            "Reformat the following job description for a Google Jobs structured listing. "
            "Google Jobs extracts schema.org/JobPosting data so use very clear headings. "
            "Required sections: Job Overview (3 sentences), Key Responsibilities (bullets), "
            "Required Qualifications (bullets), Preferred Qualifications (bullets), "
            "Compensation & Benefits, About the Company. "
            "Be precise and factual. Under 700 words."
        ),
    },
]


async def _publish(
    platform_id: str,
    session_id: str,
    title: str,
    formatted_content: str,
) -> str:
    """
    Call the real platform API. Returns the post/feed URL.
    Raises on hard failure; caller decides whether to yield an error event.
    """
    if platform_id == "linkedin":
        if not settings.linkedin_access_token or not settings.linkedin_author_urn:
            # Demo mode — simulate a successful post without real credentials
            logger.info("LinkedIn credentials not set — running in demo mode")
            return f"https://www.linkedin.com/jobs/view/demo-{session_id[:8]}"
        return await post_to_linkedin(
            access_token=settings.linkedin_access_token,
            author_urn=settings.linkedin_author_urn,
            title=title,
            formatted_content=formatted_content,
        )

    if platform_id == "indeed":
        return await post_to_indeed(
            session_id=session_id,
            title=title,
            formatted_content=formatted_content,
            base_url=settings.app_base_url,
            publisher_id=settings.indeed_publisher_id or None,
        )

    if platform_id == "google_jobs":
        return await post_to_google_jobs(
            session_id=session_id,
            title=title,
            formatted_content=formatted_content,
            base_url=settings.app_base_url,
            service_account_json=settings.google_service_account_json or None,
        )

    raise ValueError(f"Unknown platform: {platform_id}")


async def stream_job_postings(
    jd_content: str,
    title: str,
    session_id: str,
) -> AsyncGenerator[str, None]:
    """Yield NDJSON lines as each platform posting is formatted and published."""
    for platform in _PLATFORMS:
        logger.info(f"Job poster: formatting for {platform['name']}")
        yield json.dumps({"type": "start", "platform": platform["name"]}) + "\n"

        # ── Step 1: reformat with OpenAI ────────────────────────────────────
        accumulated: list[str] = []
        try:
            stream = await _client.chat.completions.create(
                model=settings.openai_model,
                stream=True,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert recruitment copywriter. "
                            "Your task is to reformat job descriptions for specific job boards. "
                            "Output only the reformatted job post — no preamble, no commentary."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"{platform['instructions']}\n\n"
                            f"--- ORIGINAL JD ---\n{jd_content}"
                        ),
                    },
                ],
            )

            async for event in stream:
                chunk = event.choices[0].delta.content or ""
                if chunk:
                    accumulated.append(chunk)
                    yield json.dumps({
                        "type": "chunk",
                        "platform": platform["name"],
                        "text": chunk,
                    }) + "\n"

        except Exception as exc:
            logger.error(f"Job poster OpenAI error on {platform['name']}: {exc}")
            yield json.dumps({
                "type": "error",
                "platform": platform["name"],
                "message": f"Formatting failed: {exc}",
            }) + "\n"
            continue

        # ── Step 2: publish to the real platform API ─────────────────────────
        formatted_content = "".join(accumulated)
        try:
            url = await _publish(platform["id"], session_id, title, formatted_content)
        except Exception as exc:
            logger.error(f"Job poster publish error on {platform['name']}: {exc}")
            yield json.dumps({
                "type": "error",
                "platform": platform["name"],
                "message": str(exc),
            }) + "\n"
            continue

        logger.info(f"Job poster: published to {platform['name']} | url={url}")
        yield json.dumps({
            "type": "posted",
            "platform": platform["name"],
            "platform_id": platform["id"],
            "url": url,
            "content": formatted_content,
        }) + "\n"

    yield json.dumps({"type": "done"}) + "\n"