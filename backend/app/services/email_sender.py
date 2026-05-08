"""
Email sender — SMTP-based email dispatch for Invictus Hiring.

Sends:
  - Interview invitation emails (HR-approved, sent to candidate)
  - Password reset emails
  - Application confirmation emails (sent to candidate on submission)

Fails gracefully when SMTP is not configured (smtp_host empty):
  every send_ function returns False and logs a warning instead of raising.

Local dev: point SMTP_HOST=localhost SMTP_PORT=1025 at the Mailhog container.
  All sent emails are visible at http://localhost:8025 — nothing is delivered for real.
"""

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from app.core.config import settings

# ── Shared HTML shell ─────────────────────────────────────────────────────────

_HTML_SHELL = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f5f3ff;font-family:Inter,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f3ff;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;overflow:hidden;
                    box-shadow:0 2px 8px rgba(0,0,0,0.08);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#7c3aed,#6d28d9);
                     padding:28px 36px;">
            <span style="color:#ffffff;font-size:20px;font-weight:700;
                         letter-spacing:-0.3px;">Invictus Hiring</span>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px;color:#1c1917;font-size:15px;line-height:1.7;">
            {body}
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="padding:20px 36px;background:#faf5ff;border-top:1px solid #ede9fe;
                     font-size:12px;color:#78716c;text-align:center;">
            Invictus Hiring · AI-powered recruitment platform<br/>
            This email was sent automatically — please do not reply.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def _html(subject: str, body_html: str) -> str:
    return _HTML_SHELL.format(subject=subject, body=body_html)


# ── Low-level SMTP send ───────────────────────────────────────────────────────

def _send_sync(to: str, subject: str, plain: str, html: str) -> None:
    """Blocking SMTP send — run via asyncio.to_thread."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, [to], msg.as_string())


async def _send(to: str, subject: str, plain: str, html: str) -> bool:
    """
    Async wrapper around _send_sync.
    Returns True on success, False if SMTP is not configured, raises on SMTP error.
    """
    if not settings.smtp_host:
        logger.info(f"SMTP not configured — skipping email to {to!r} subject={subject!r}")
        return False
    await asyncio.to_thread(_send_sync, to, subject, plain, html)
    logger.info(f"Email sent | to={to!r} subject={subject!r}")
    return True


# ── Email: interview invitation ───────────────────────────────────────────────

async def send_interview_email(to: str, subject: str, body: str) -> bool:
    """
    Send the HR-approved interview invitation to a candidate.
    Returns True if sent, False if SMTP not configured.
    Raises on SMTP error so the caller can store the error message.
    """
    html_body = f"""
        <h2 style="margin:0 0 16px;font-size:20px;color:#6d28d9;">Interview Invitation</h2>
        <div style="white-space:pre-wrap;">{body}</div>
        <p style="margin:28px 0 0;font-size:13px;color:#78716c;">
          If you have any questions, please reply to your recruitment contact.
        </p>
    """
    return await _send(to, subject, body, _html(subject, html_body))


# ── Email: password reset ─────────────────────────────────────────────────────

async def send_password_reset_email(to: str, reset_token: str) -> bool:
    """
    Send a password reset link to the user.
    Returns True if sent, False if SMTP not configured.
    """
    reset_url = f"{settings.app_base_url.replace('8000', '3000')}/reset-password?token={reset_token}"
    subject = "Reset your Invictus Hiring password"
    plain = (
        f"Hi,\n\nYou requested a password reset for your Invictus Hiring account.\n\n"
        f"Click the link below to reset your password (valid for 30 minutes):\n{reset_url}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"— Invictus Hiring"
    )
    html_body = f"""
        <h2 style="margin:0 0 16px;font-size:20px;color:#6d28d9;">Reset your password</h2>
        <p>You requested a password reset for your Invictus Hiring account.</p>
        <p>Click the button below to choose a new password. This link is valid for <strong>30 minutes</strong>.</p>
        <p style="margin:28px 0;">
          <a href="{reset_url}"
             style="display:inline-block;background:#7c3aed;color:#fff;text-decoration:none;
                    padding:12px 28px;border-radius:8px;font-weight:600;font-size:15px;">
            Reset Password
          </a>
        </p>
        <p style="font-size:13px;color:#78716c;">
          Or copy this link into your browser:<br/>
          <a href="{reset_url}" style="color:#7c3aed;">{reset_url}</a>
        </p>
        <p style="font-size:13px;color:#78716c;margin-top:24px;">
          If you didn't request a password reset, you can safely ignore this email —
          your password will not be changed.
        </p>
    """
    return await _send(to, subject, plain, _html(subject, html_body))


# ── Email: application confirmation ──────────────────────────────────────────

async def send_application_confirmation_email(
    to: str,
    candidate_name: str,
    job_title: str,
    company: str = "Invictus Hiring",
) -> bool:
    """
    Send an acknowledgement to the candidate after they submit an application.
    Returns True if sent, False if SMTP not configured.
    """
    subject = f"Application received — {job_title}"
    plain = (
        f"Hi {candidate_name},\n\n"
        f"Thank you for applying for the {job_title} role at {company}.\n\n"
        f"We've received your application and our team will review it shortly. "
        f"If your profile matches what we're looking for, we'll be in touch to arrange next steps.\n\n"
        f"Best of luck!\n\n— The {company} hiring team"
    )
    html_body = f"""
        <h2 style="margin:0 0 16px;font-size:20px;color:#6d28d9;">
          Application received ✓
        </h2>
        <p>Hi <strong>{candidate_name}</strong>,</p>
        <p>
          Thank you for applying for the <strong>{job_title}</strong> role at
          <strong>{company}</strong>.
        </p>
        <p>
          We've received your application and our team will review it shortly.
          If your profile matches what we're looking for, we'll be in touch to
          arrange the next steps.
        </p>
        <p style="margin-top:28px;">Best of luck!</p>
        <p style="color:#78716c;">— The {company} hiring team</p>
    """
    return await _send(to, subject, plain, _html(subject, html_body))