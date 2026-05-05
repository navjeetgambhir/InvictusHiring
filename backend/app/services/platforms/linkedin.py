"""
LinkedIn UGC Posts API integration.

Posts an approved JD as a public LinkedIn post on behalf of the configured user
or organisation. Uses the LinkedIn REST API v2.

Required env vars:
    LINKEDIN_ACCESS_TOKEN  — OAuth 2.0 bearer token (scope: w_member_social or
                             w_organization_social + r_organization_social)
    LINKEDIN_AUTHOR_URN    — e.g. "urn:li:person:ABC123" or "urn:li:organization:12345"

How to get a token (one-time setup):
  1. Create a LinkedIn Developer App at https://www.linkedin.com/developers/apps
  2. Add OAuth 2.0 scopes: w_member_social, r_liteprofile
  3. Generate an access token via the OAuth 2.0 token inspector in the app dashboard
     (or run the 3-legged OAuth flow once and store the token)
  4. Copy the person URN from GET https://api.linkedin.com/v2/me  → "id" field,
     then prefix with "urn:li:person:"
"""

import httpx
from loguru import logger

_API_BASE = "https://api.linkedin.com/v2"
_MAX_TEXT_LEN = 2900  # LinkedIn UGC post text limit is ~3 000 chars


def _truncate(text: str, limit: int = _MAX_TEXT_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "…"


async def post_to_linkedin(
    access_token: str,
    author_urn: str,
    title: str,
    formatted_content: str,
) -> str:
    """
    Publish a job post to LinkedIn. Returns the URL of the created post.
    Raises httpx.HTTPStatusError on API errors.
    """
    headline = f"🚀 We're hiring: {title}\n\n"
    body = _truncate(headline + formatted_content)

    payload = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": body},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{_API_BASE}/ugcPosts",
            json=payload,
            headers=headers,
        )

    response.raise_for_status()

    # LinkedIn returns the new post's URN in the X-RestLi-Id header
    post_urn = response.headers.get("x-restli-id", "")
    # URN looks like urn:li:ugcPost:1234567890 — build a share URL from it
    post_id = post_urn.split(":")[-1] if post_urn else ""
    url = (
        f"https://www.linkedin.com/feed/update/{post_urn}/"
        if post_urn
        else "https://www.linkedin.com/jobs/"
    )

    logger.info(f"LinkedIn post created | urn={post_urn} url={url}")
    return url