"""Per-step worker email allowance, shared through the notification ledger.

API mail and Supabase Auth SMTP are outside this ledger; the default 15-email
headroom covers them. The digest leaves a further reserve for later steps.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.config import get_settings

logger = logging.getLogger(__name__)


def utc_midnight(now: datetime) -> datetime:
    current = (
        now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    )
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


def sent_today(session: Session, now: datetime) -> int:
    """One range query; never wrap sent_at in a date function.

    Count sent email rows conservatively: legacy grouped company/deadline
    emails can have several rows. Auth/API emails use the reserved headroom.
    """
    return (
        session.scalar(
            select(func.count(models.Notification.id)).where(
                models.Notification.channel == "email",
                models.Notification.status == "sent",
                models.Notification.sent_at >= utc_midnight(now),
            )
        )
        or 0
    )


@dataclass
class EmailBudget:
    """Snapshot once per worker step, then account locally without queries."""

    sent_today: int
    budget: int
    digest_reserve: int
    sent: int = 0
    deferred: int = 0

    @classmethod
    def for_step(cls, session: Session, now: datetime) -> "EmailBudget":
        settings = get_settings()
        return cls(
            sent_today(session, now), settings.email_daily_budget, settings.email_digest_reserve
        )

    def remaining(self) -> int:
        return max(0, self.budget - self.sent_today - self.sent)

    def can_send(self, kind: str) -> bool:
        return self.remaining() > (self.digest_reserve if kind == "digest" else 0)

    def record_sent(self) -> None:
        self.sent += 1

    def log(self) -> None:
        logger.info(
            "email budget: sent_today=%d budget=%d remaining=%d deferred=%d",
            self.sent_today,
            self.budget,
            self.remaining(),
            self.deferred,
        )
