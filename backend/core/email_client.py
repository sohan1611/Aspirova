"""Public mail seam: durable outbox by default, transport only with a lease."""

import httpx
import uuid
from sqlalchemy.orm import Session

from core.config import get_settings
from core.email_outbox import ProviderResult


def send_email(
    to: str,
    subject: str,
    html: str,
    text: str,
    headers: dict[str, str] | None = None,
    *,
    session: Session | None = None,
    kind: str = "transactional",
    identity: object = None,
    user_id: uuid.UUID | None = None,
    receipts: list[dict] | None = None,
) -> bool:
    from core import email_outbox

    active = email_outbox.current_submission.get()
    if active is None:
        # Stable content identity covers older API/founder callers. Callers with
        # a domain event provide its ID instead; retries always reuse stored bytes.
        identity = identity if identity is not None else [subject, html, text, headers]
        if session is not None:
            return email_outbox.send(
                session,
                send_email,
                to,
                subject,
                html,
                text,
                headers=headers,
                kind=kind,
                identity=identity,
                user_id=user_id,
                receipts=receipts,
            )
        from core.db import make_engine

        engine = make_engine()
        try:
            with Session(engine) as db:
                return email_outbox.send(
                    db,
                    send_email,
                    to,
                    subject,
                    html,
                    text,
                    headers=headers,
                    kind=kind,
                    identity=identity,
                    user_id=user_id,
                    receipts=receipts,
                )
        finally:
            engine.dispose()

    active.result = _transport(active.payload, active.key)
    return active.result.provider_id is not None


def _transport(payload: dict, key: str) -> ProviderResult:
    settings = get_settings()
    if not (settings.resend_api_key and settings.resend_from_email):
        return ProviderResult(code=503, message="Email provider is not configured")
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}", "Idempotency-Key": key},
            json=payload,
            timeout=20,
        )
    except (httpx.TransportError, OSError):
        return ProviderResult()
    try:
        data = response.json()
    except ValueError:
        data = {}
    if 200 <= response.status_code < 300 and isinstance(data, dict) and data.get("id"):
        return ProviderResult(code=response.status_code, provider_id=str(data["id"]))
    # Vendor messages may echo the submitted body, credentials or recipient.
    # Expose only known provider categories and a safe explanation, never raw text.
    name = data.get("name") if isinstance(data, dict) else None
    messages = {
        "validation_error": "validation_error: Invalid email address or email payload",
        "missing_required_field": "missing_required_field: Required email field is missing",
        "invalid_access": "invalid_access: Provider credentials or permissions rejected",
        "restricted_api_key": "restricted_api_key: Provider key cannot send this email",
        "rate_limit_exceeded": "rate_limit_exceeded: Provider rate limit exceeded",
        "daily_quota_exceeded": "daily_quota_exceeded: Provider daily quota exhausted",
        "invalid_idempotent_request": "invalid_idempotent_request: Key payload conflict",
        "concurrent_idempotent_requests": "concurrent_idempotent_requests: Request in progress",
    }
    message = messages.get(name, f"Provider HTTP {response.status_code}; details redacted")
    return ProviderResult(
        code=response.status_code,
        message=message,
        retry_after=response.headers.get("Retry-After"),
    )


def _format_from(name: str, email: str) -> str:
    """Return a display-name From header when one is configured."""
    if "<" in email:
        return email

    if not name.strip():
        return email

    if any(character in name for character in ',;:<>@"'):
        return f'"{name}" <{email}>'

    return f"{name} <{email}>"
