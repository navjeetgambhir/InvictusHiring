"""
Indeed UK XML job feed integration.

Indeed's standard ingestion mechanism for employer job feeds is an XML file
hosted at a public URL. You submit the feed URL once in the Indeed Employer
dashboard and Indeed crawls it periodically (or on-demand via their Employer API).

This module:
  1. Generates a valid Indeed XML job feed for a single job posting.
  2. Writes it to a well-known path served by FastAPI (/indeed-feed/{session_id}.xml).
  3. Optionally notifies Indeed's Employer API to re-index the feed immediately
     (requires INDEED_PUBLISHER_ID from https://employers.indeed.com).

Required env vars (optional — feed generation works without them):
    INDEED_PUBLISHER_ID    — from your Indeed Employer account
    APP_BASE_URL           — public base URL, e.g. https://hireflow.example.com
                             (used to build the canonical job URL in the feed)
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
from loguru import logger

# Feed files are written here and served at /indeed-feed/<name>.xml
FEED_DIR = Path(__file__).parent.parent.parent.parent / "indeed_feeds"
FEED_DIR.mkdir(exist_ok=True)


def _clean(text: str) -> str:
    """Strip control characters that are illegal in XML 1.0."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def generate_xml_feed(
    session_id: str,
    title: str,
    company: str,
    location: str,
    salary: str,
    job_type: str,
    description: str,
    base_url: str,
) -> str:
    """Return a valid Indeed XML feed string for a single job."""
    ref = str(uuid.uuid4())[:8].upper()
    job_url = f"{base_url.rstrip('/')}/jobs/{session_id}"
    posted_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<source>
  <publisher>{escape(_clean(company))}</publisher>
  <publisherurl>{escape(base_url)}</publisherurl>
  <lastBuildDate>{posted_date}</lastBuildDate>
  <job>
    <title><![CDATA[{_clean(title)}]]></title>
    <date><![CDATA[{posted_date}]]></date>
    <referencenumber><![CDATA[{ref}]]></referencenumber>
    <url><![CDATA[{job_url}]]></url>
    <company><![CDATA[{_clean(company)}]]></company>
    <city><![CDATA[{_clean(location)}]]></city>
    <country><![CDATA[United Kingdom]]></country>
    <description><![CDATA[{_clean(description)}]]></description>
    <salary><![CDATA[{_clean(salary)}]]></salary>
    <jobtype><![CDATA[{_clean(job_type)}]]></jobtype>
    <remotetype><![CDATA[]]></remotetype>
  </job>
</source>"""
    return xml


def save_feed(session_id: str, xml: str) -> Path:
    path = FEED_DIR / f"{session_id}.xml"
    path.write_text(xml, encoding="utf-8")
    return path


async def notify_indeed(publisher_id: str, feed_url: str) -> None:
    """
    Ping Indeed's Employer API to re-crawl the feed immediately.
    https://ads.indeed.com/jobroll/xmlfeed  (requires publisher approval)
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://ads.indeed.com/jobroll/xmlfeed",
            params={"publisher": publisher_id, "url": feed_url},
        )
    if resp.is_success:
        logger.info(f"Indeed feed notified | publisher={publisher_id}")
    else:
        logger.warning(f"Indeed notify returned {resp.status_code}: {resp.text[:200]}")


async def post_to_indeed(
    session_id: str,
    title: str,
    formatted_content: str,
    base_url: str,
    publisher_id: str | None,
    company: str = "InvictusHiring",
    location: str = "United Kingdom",
    salary: str = "",
    job_type: str = "Full-time",
) -> str:
    """
    Generate the Indeed XML feed, persist it, and optionally notify Indeed.
    Returns the URL where the feed is publicly accessible.
    """
    xml = generate_xml_feed(
        session_id=session_id,
        title=title,
        company=company,
        location=location,
        salary=salary,
        job_type=job_type,
        description=formatted_content,
        base_url=base_url,
    )
    save_feed(session_id, xml)
    feed_url = f"{base_url.rstrip('/')}/indeed-feed/{session_id}.xml"

    if publisher_id:
        try:
            await notify_indeed(publisher_id, feed_url)
        except Exception as exc:
            logger.warning(f"Indeed notify failed (non-fatal): {exc}")

    logger.info(f"Indeed XML feed ready | url={feed_url}")
    return feed_url