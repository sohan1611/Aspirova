"""One-click unsubscribe tokens for bulk email (Gmail bulk-sender rules).

Gmail has required `List-Unsubscribe` plus `List-Unsubscribe-Post` on bulk mail
since February 2024. Mail without them is filtered hard or accepted and silently
discarded - which is exactly the symptom seen here: Resend reported `delivered`
for every recipient while the message was in nobody's mailbox, spam included.

The header must point at something that unsubscribes WITHOUT a login and without
a confirmation page, because Gmail POSTs to it directly on the reader's behalf.
The existing footer link goes to `/account?section=notifications`, which requires
a session - fine for a human, useless to Gmail.

So each email carries a per-recipient signed token. The token IS the
authorisation: it names one user and one preference key, it is signed, and it
grants nothing except turning that one preference off.

The signing key must be IDENTICAL in two places: the notification worker (GitHub
Actions) signs the token, and the API (Render) verifies it. Production proved on
2026-10-18 that DATABASE_URL is not a shared secret contract: a real worker token
verified under the GitHub DATABASE_URL-derived key, while the current Render API
returned HTTP 200 without changing notification_prefs. Zero of 40 users had a
token-based opt-out. A byte-level URL difference (host, port, query, or driver)
is enough to make every signature fail, and a database migration invalidates all
outstanding links.

UNSUBSCRIBE_SECRET is therefore the primary and required production key. The
DATABASE_URL fallback remains only so a missing secret degrades to the old
header-producing behaviour instead of dropping List-Unsubscribe from bulk mail.
It logs a process-level warning, and the digest guard compares a safe truncated
fingerprint with the API before sending. The same UNSUBSCRIBE_SECRET must be set
in GitHub Actions and Render.

Whatever the source, it is never used raw: the key is a domain-separated HMAC of
it, so a leaked token reveals nothing about the credential behind it. Set
UNSUBSCRIBE_SECRET in BOTH environments for proper key separation; doing so
invalidates outstanding links, which is harmless since the next email carries new
ones.
"""

import base64
import hashlib
import hmac
import logging
import threading
import uuid  # noqa: F401  - used in type hints only

from core.config import get_settings

logger = logging.getLogger(__name__)

_DOMAIN = b"aspirova.unsubscribe.v1"
_SIG_LENGTH = 32  # hex chars of SHA-256 => 128 bits, far beyond brute force
_fallback_warning_lock = threading.Lock()
_fallback_warning_emitted = False


def _warn_database_url_fallback() -> None:
    """Emit the migration-risk warning once even under concurrent requests."""
    global _fallback_warning_emitted

    if _fallback_warning_emitted:
        return
    with _fallback_warning_lock:
        if _fallback_warning_emitted:
            return
        logger.warning(
            "UNSUBSCRIBE_SECRET is unset; the unsubscribe signing key is "
            "DATABASE_URL-derived and will break when the database changes. "
            "Set UNSUBSCRIBE_SECRET to the same value in GitHub Actions and Render."
        )
        _fallback_warning_emitted = True


def _signing_key() -> bytes:
    settings = get_settings()
    explicit = (getattr(settings, "unsubscribe_secret", "") or "").strip()
    database_url = (settings.database_url or "").strip()
    base = explicit or database_url
    if not base:
        # No header is emitted rather than a broken one - see
        # list_unsubscribe_headers.
        logger.warning("unsubscribe signing key unavailable; List-Unsubscribe will be omitted")
        return b""
    if not explicit:
        _warn_database_url_fallback()
    return hmac.new(base.encode(), _DOMAIN, hashlib.sha256).digest()


def key_fingerprint() -> str:
    """Identify the active derived key without revealing key material."""
    key = _signing_key()
    if not key:
        return ""
    return hashlib.sha256(key).hexdigest()[:12]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def make_token(user_id: "uuid.UUID | str", preference_key: str) -> str:
    """Sign a token naming exactly one user and one preference."""
    key = _signing_key()
    if not key:
        return ""
    payload = f"{user_id}:{preference_key}"
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:_SIG_LENGTH]
    return f"{_b64(payload.encode())}.{signature}"


def verify_token(token: str) -> tuple[str, str] | None:
    """Return (user_id, preference_key) for a valid token, else None.

    The user id is returned as a STRING and never coerced. users.id is a UUID
    (it mirrors Supabase auth.users.id); an earlier version cast it to int,
    which raised on every real token and silently disabled the whole feature -
    tokens signed fine and verification always returned None.

    Never raises on malformed input: this is reached by unauthenticated
    requests, so every parse failure is just an invalid token.
    """
    key = _signing_key()
    if not key or not token or "." not in token:
        return None

    encoded, _, signature = token.partition(".")
    try:
        payload = _unb64(encoded).decode()
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return None

    user_id, _, preference_key = payload.partition(":")
    if not user_id or not preference_key:
        return None

    expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:_SIG_LENGTH]
    # Constant time: a timing oracle here would let a signature be recovered
    # byte by byte.
    if not hmac.compare_digest(expected, signature):
        return None

    return user_id, preference_key


def unsubscribe_url(user_id: "uuid.UUID | str", preference_key: str) -> str:
    """Absolute URL Gmail will POST to. Empty when signing is unconfigured."""
    token = make_token(user_id, preference_key)
    if not token:
        return ""
    settings = get_settings()
    base = (settings.api_base_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/notifications/unsubscribe?token={token}"


def list_unsubscribe_headers(user_id: "uuid.UUID | str", preference_key: str) -> dict[str, str]:
    """The two headers Gmail looks for. Empty dict if it cannot be built.

    Returning {} rather than a broken header is deliberate - a List-Unsubscribe
    pointing at a URL that cannot work is worse than none, because the reader
    clicks it and nothing happens.
    """
    url = unsubscribe_url(user_id, preference_key)
    if not url:
        return {}
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
