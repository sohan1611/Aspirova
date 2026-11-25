"""Per-step display snapshot of the durable application email attempt budget.

All Resend HTTP mail shares 85 slots; Supabase Auth SMTP remains outside the
application's send path with 15 slots of headroom. Digests leave 10 slots for
other kinds. The authoritative concurrent check lives in email_outbox.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, union_all
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
    """One query: durable attempt reservations plus pre-outbox successful sends.

    Each retry costs a slot, even if it times out or a worker crashes. Legacy
    ledger rows count until UTC midnight on deployment day; no backfill needed.
    """
    events = union_all(
        select(models.EmailAttempt.outbox_id.label("id")).where(
            models.EmailAttempt.started_at >= utc_midnight(now),
            models.EmailAttempt.started_at < utc_midnight(now) + timedelta(days=1),
        ),
        select(models.Notification.id).where(
            models.Notification.channel == "email",
            models.Notification.status == "sent",
            models.Notification.outbox_id.is_(None),
            models.Notification.sent_at >= utc_midnight(now),
            models.Notification.sent_at < utc_midnight(now) + timedelta(days=1),
        ),
    ).subquery()
    reservations = (
        select(models.EmailBudgetDay.used)
        .where(models.EmailBudgetDay.day == utc_midnight(now).date())
        .scalar_subquery()
    )
    return (
        session.scalar(
            select(func.greatest(func.count(), func.coalesce(reservations, 0))).select_from(events)
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
