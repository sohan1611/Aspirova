"""Thin wrapper around Resend (Doc 02 sec 3.6). Every notification send
goes through here - one place to swap providers later (AWS SES at scale,
per Doc 02/06) without touching the worker logic in pipeline/notifications.py.

Never raises: a missing API key or a Resend-side failure returns False and
logs, so one failed send cannot take down the rest of a notification
batch (Doc 04 sec 7's per-source isolation principle, applied here to
per-user email sends).
"""

import logging

import resend

from core.config import get_settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html: str, text: str) -> bool:
    settings = get_settings()
    if not (settings.resend_api_key and settings.resend_from_email):
        logger.warning("RESEND_API_KEY/RESEND_FROM_EMAIL not configured - email not sent to %s", to)
        return False

    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send(
            {
                "from": _format_from(settings.resend_from_name, settings.resend_from_email),
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            }
        )
        return True
    except Exception:
        logger.warning("email send failed for %s", to, exc_info=True)
        return False


def _format_from(name: str, email: str) -> str:
    """Return a display-name From header when one is configured."""
    if "<" in email:
        return email

    if not name.strip():
        return email

    if any(character in name for character in ',;:<>@"'):
        return f'"{name}" <{email}>'

    return f"{name} <{email}>"
