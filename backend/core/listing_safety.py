"""Founder-owned safety state, separate from premium visibility and crawl data."""

from urllib.parse import urlsplit

from core import models


def safety_flag(opportunity: models.Opportunity) -> dict | None:
    meta = opportunity.meta
    value = meta.get("safety") if isinstance(meta, dict) else None
    return value if isinstance(value, dict) else None


def without_safety_flag():
    """Fail closed for any stored safety key, including malformed legacy values."""
    return models.Opportunity.meta["safety"].astext.is_(None)


def source_reference(opportunity: models.Opportunity, *, safety: bool) -> str | None:
    """A safety reference must never fall back to the potentially unsafe apply URL."""
    flag = safety_flag(opportunity) or {}
    values = (
        (flag.get("source_url"),) if safety else (flag.get("source_url"), opportunity.apply_url)
    )
    for value in values:
        if isinstance(value, str):
            try:
                parsed = urlsplit(value)
                if parsed.scheme in {"https", "http"} and parsed.hostname:
                    return value
            except ValueError:
                continue
    return None
