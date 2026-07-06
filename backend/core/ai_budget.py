"""Daily AI-spend guardrail used by later feature degradation checks."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import AiUsage


def get_daily_spend(session: Session, *, now: datetime | None = None) -> float:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    total = session.scalar(
        select(func.coalesce(func.sum(AiUsage.est_cost), 0.0)).where(
            AiUsage.created_at >= day_start,
            AiUsage.created_at < day_end,
        )
    )
    return float(total)


def is_over_budget(session: Session, *, now: datetime | None = None) -> bool:
    return get_daily_spend(session, now=now) >= get_settings().ai_daily_usd_cap
