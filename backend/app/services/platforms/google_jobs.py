"""
Google Jobs integration via JSON-LD + Google Indexing API.

Google Jobs does not have a direct "post a job" endpoint. Jobs appear in Google
search results when a page contains valid schema.org/JobPosting JSON-LD markup.

This module:
  1. Generates a schema.org/JobPosting JSON-LD document for the approved JD.
  2. Persists it so FastAPI can serve it at /jobs/{session_id} with the correct
     HTML wrapper (the page Google's crawler will index).
  3. Calls the Google Indexing API to notify Google that the URL is ready to crawl,
     so the job appears in results within minutes rather than days.

Required env vars (optional — JSON-LD generation works without them):
    GOOGLE_SERVICE_ACCOUNT_JSON  — JSON string of a GCP service account key file
                                   (the service account must be verified as a site
                                    owner in Google Search Console for APP_BASE_URL)
    APP_BASE_URL                 — public base URL, e.g. https://hireflow.example.com

Google setup (one-time):
  1. Create a project at https://console.cloud.google.com
  2. Enable "Web Search Indexing API"
  3. Create a service account → download JSON key
  4. Verify site ownership in Google Search Console → add the service account email
     as a "Delegated owner"
"""

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from loguru import logger

# Rendered job pages are stored here and served at /jobs/<session_id>
JOBS_DIR = Path(__file__).parent.parent.parent.parent / "job_pages"
JOBS_DIR.mkdir(exist_ok=True)

_INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
_INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"


def build_json_ld(
    session_id: str,
    title: str,
    description: str,
    location: str,
    salary: str,
    job_type: str,
    company: str,
    base_url: str,
) -> dict:
    """Return a schema.org/JobPosting dict."""
    now = datetime.now(timezone.utc).date().isoformat()
    job_url = f"{base_url.rstrip('/')}/jobs/{session_id}"

    schema: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "description": description,
        "datePosted": now,
        "hiringOrganization": {
            "@type": "Organization",
            "name": company,
            "sameAs": base_url,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": location,
                "addressCountry": "GB",
            },
        },
        "employmentType": job_type.upper().replace("-", "_"),
        "url": job_url,
        "identifier": {
            "@type": "PropertyValue",
            "name": company,
            "value": session_id,
        },
    }

    # Add salary if we can extract a number range
    numbers = re.findall(r"[\d,]+", salary.replace("£", "").replace("k", "000"))
    if len(numbers) >= 2:
        schema["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": "GBP",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": float(numbers[0].replace(",", "")),
                "maxValue": float(numbers[1].replace(",", "")),
                "unitText": "YEAR",
            },
        }

    return schema


def _render_html_page(title: str, company: str, json_ld: dict) -> str:
    """Wrap JSON-LD in a minimal HTML page that Google can crawl."""
    ld_str = json.dumps(json_ld, indent=2)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {company}</title>
  <script type="application/ld+json">
{ld_str}
  </script>
</head>
<body>
  <h1>{title}</h1>
  <p><strong>{company}</strong></p>
  <pre style="white-space:pre-wrap">{json_ld.get('description', '')}</pre>
</body>
</html>"""


def save_job_page(session_id: str, html: str) -> Path:
    path = JOBS_DIR / f"{session_id}.html"
    path.write_text(html, encoding="utf-8")
    return path


async def _notify_google_indexing(job_url: str, service_account_json: str) -> None:
    """Call the Google Indexing API using a service account JWT."""
    try:
        sa = json.loads(service_account_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid GOOGLE_SERVICE_ACCOUNT_JSON: {exc}") from exc

    # Build a self-signed JWT for the service account
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=")

    now = int(time.time())
    claims = {
        "iss": sa["client_email"],
        "scope": _INDEXING_SCOPE,
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    claims_b64 = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=")

    signing_input = header + b"." + claims_b64

    # Sign with RSA-SHA256 using the service account private key
    private_key = serialization.load_pem_private_key(
        sa["private_key"].encode(), password=None
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")

    jwt_token = (signing_input + b"." + sig_b64).decode()

    async with httpx.AsyncClient(timeout=15) as client:
        # Exchange JWT for access token
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt_token,
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        # Notify the Indexing API
        index_resp = await client.post(
            _INDEXING_ENDPOINT,
            json={"url": job_url, "type": "URL_UPDATED"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        index_resp.raise_for_status()

    logger.info(f"Google Indexing API notified | url={job_url}")


async def post_to_google_jobs(
    session_id: str,
    title: str,
    formatted_content: str,
    base_url: str,
    service_account_json: str | None,
    company: str = "InvictusHiring",
    location: str = "United Kingdom",
    salary: str = "",
    job_type: str = "FULL_TIME",
) -> str:
    """
    Build JSON-LD, render an HTML page, persist it, optionally ping Google.
    Returns the public job page URL.
    """
    job_url = f"{base_url.rstrip('/')}/jobs/{session_id}"

    json_ld = build_json_ld(
        session_id=session_id,
        title=title,
        description=formatted_content,
        location=location,
        salary=salary,
        job_type=job_type,
        company=company,
        base_url=base_url,
    )
    html = _render_html_page(title, company, json_ld)
    save_job_page(session_id, html)

    if service_account_json:
        try:
            await _notify_google_indexing(job_url, service_account_json)
        except Exception as exc:
            logger.warning(f"Google Indexing API notify failed (non-fatal): {exc}")

    logger.info(f"Google Jobs page ready | url={job_url}")
    return job_url