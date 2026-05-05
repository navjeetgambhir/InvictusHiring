"""
Email sender — wraps smtplib for sending interview invitation emails.

Fails gracefully if SMTP is not configured (smtp_host is empty):
the invitation is marked approved but no email is dispatched.
"""

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from app.core.config import settings


def _send_sync(to: str, subject: str, body: str) -> None:
    """Blocking SMTP send — run via asyncio.to_thread."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, [to], msg.as_string())


async def send_interview_email(to: str, subject: str, body: str) -> bool:
    """
    Send the interview invitation email.

    Returns True if sent, False if SMTP is not configured (graceful no-op).
    Raises on SMTP error so the caller can store the error message.
    """
    if not settings.smtp_host:
        logger.info(
            f"SMTP not configured — invitation approved but not emailed "
            f"(would send to {to}, subject='{subject[:60]}')"
        )
        return False

    await asyncio.to_thread(_send_sync, to, subject, body)
    logger.info(f"Interview invitation email sent to {to}")
    return True