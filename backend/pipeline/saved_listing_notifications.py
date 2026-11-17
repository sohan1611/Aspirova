"""Free saved-listing safety and unexpected closure events (ALERT-04).

In-app rows are durable independently of email. email_pending is consumed only
after transport acceptance. The caller holds the recipient lock and commits.
One catalogue query per run buckets early closures over the last eight days.
Each settled candidate is held when its own +/-24-hour window exceeds the
configured threshold, even on later runs; safety notices bypass this breaker.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from core import models
from core.config import get_settings
from core.email_components import listing_url, opportunity_card, section
from core.listing_safety import safety_flag, source_reference

logger = logging.getLogger(__name__)
# The current tracker has only one pre-application state. Archived is not pending.
PRE_APPLICATION_STATUSES = ("saved",)
SAVED_EVENT_TYPES = ("saved_closed", "saved_safety")
SAFETY_ADVICE = "Do not pay any fee or share bank or ID documents."


def closed_early_filters(now: datetime, *, lookback: timedelta) -> tuple:
    return (
        models.Opportunity.status != "withdrawn",
        models.Opportunity.closed_at.is_not(None),
        models.Opportunity.closed_at >= now - lookback,
        models.Opportunity.closed_at <= now,
        or_(
            models.Opportunity.deadline.is_(None),
            models.Opportunity.closed_at < models.Opportunity.deadline,
        ),
    )


@dataclass
class ClosureNoticeBreaker:
    buckets: list[tuple[datetime, int]]
    threshold: int
    held_candidates: int = 0
    largest_window_count: int = 0

    def holds(self, closed_at: datetime) -> bool:
        """Judge the closure's fixed window, never a window relative to this run."""
        start, end = closed_at - timedelta(hours=24), closed_at + timedelta(hours=24)
        count = sum(count for hour, count in self.buckets if start <= hour <= end)
        if count <= self.threshold:
            return False
        self.held_candidates += 1
        self.largest_window_count = max(self.largest_window_count, count)
        return True

    def log_held(self) -> None:
        if self.held_candidates:
            logger.warning(
                "Saved closure notice breaker: held %d candidates; largest window count %d "
                "(24 hours either side of the listing's closure)",
                self.held_candidates,
                self.largest_window_count,
            )


def load_closure_notice_breaker(session: Session, now: datetime) -> ClosureNoticeBreaker:
    """Read hourly catalogue counts once, including the oldest candidate's full window."""
    hour = func.date_trunc("hour", models.Opportunity.closed_at)
    buckets = session.execute(
        select(hour, func.count(models.Opportunity.id))
        .where(*closed_early_filters(now, lookback=timedelta(days=8)))
        .group_by(hour)
        .order_by(hour)
    ).all()
    return ClosureNoticeBreaker(list(buckets), get_settings().saved_closure_notice_breaker)


def collect_saved_listing_changes(
    session: Session, user: models.User, now: datetime, *, breaker: ClosureNoticeBreaker
) -> list[tuple[models.Notification, models.Opportunity]]:
    """Create each in-app event once and return still-eligible email-pending rows."""
    enabled = not isinstance(user.notification_prefs, dict) or (
        user.notification_prefs.get("closing_soon") is not False
    )
    existing = {
        (row.type, row.opportunity_id): row
        for row in session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.type.in_(SAVED_EVENT_TYPES),
            )
        )
    }
    base = (
        select(models.Opportunity)
        .join(models.Bookmark, models.Bookmark.opportunity_id == models.Opportunity.id)
        .options(joinedload(models.Opportunity.company))
        .where(models.Bookmark.user_id == user.id)
    )
    safety = list(session.scalars(base.where(models.Opportunity.status == "withdrawn")))
    closed = [
        opportunity
        for opportunity in session.scalars(
            base.where(
                models.Bookmark.status.in_(PRE_APPLICATION_STATUSES),
                *closed_early_filters(now, lookback=timedelta(days=7)),
                models.Opportunity.closed_at <= now - timedelta(hours=24),
                models.Bookmark.created_at < models.Opportunity.closed_at,
            )
        )
        if opportunity.closed_at is not None and not breaker.holds(opportunity.closed_at)
    ]
    pending = []
    live_keys = set()
    for kind, items in (("saved_safety", safety), ("saved_closed", closed)):
        for opportunity in items:
            key = (kind, opportunity.id)
            live_keys.add(key)
            row = existing.get(key)
            if row is None:
                row = models.Notification(
                    user_id=user.id,
                    opportunity_id=opportunity.id,
                    type=kind,
                    channel="in_app",
                    status="sent",
                    sent_at=now,
                    meta={
                        "email_pending": enabled,
                        "safety": safety_flag(opportunity),
                        "closed_at": (
                            opportunity.closed_at.isoformat() if opportunity.closed_at else None
                        ),
                    },
                )
                session.add(row)
            if not enabled:
                row.meta = {**(row.meta or {}), "email_pending": False}
            if enabled and (row.meta or {}).get("email_pending"):
                pending.append((row, opportunity))
    for key, row in existing.items():
        if not enabled or key not in live_keys:
            row.meta = {**(row.meta or {}), "email_pending": False}
    session.flush()
    return pending


def render_saved_notices(
    opportunities: list[models.Opportunity], *, safety: bool, now: datetime
) -> tuple[str, str]:
    if not opportunities:
        return "", ""
    heading = "Safety warnings" if safety else "Closed early"
    cards, plain = [], []
    for opportunity in opportunities:
        flag = safety_flag(opportunity) or {}
        company = opportunity.company.name if opportunity.company else "Unknown company"
        if safety:
            label = "reported as a scam" if flag.get("kind") == "scam" else "withdrawn"
            message = f"‘{opportunity.title}’ was {label}. {flag.get('note', '')}"
            message += f" {SAFETY_ADVICE}"
            source_label = "Read the source of this warning"
        else:
            message = f"‘{opportunity.title}’ at {company} stopped accepting applications."
            source_label = "View the original source listing"
        reference = source_reference(opportunity, safety=safety)
        html, text = opportunity_card(
            opportunity,
            now=now,
            button_url=listing_url(opportunity),
            button_label="Review listing warning" if safety else "Review saved listing",
            deadline_policy="none",
            extra_html=f"<p>{escape(message)}</p>",
            secondary_link=(source_label, reference) if reference else None,
        )
        cards.append(html)
        plain.append(f"{message}\n{text}")
    return section(heading, len(cards), "".join(cards)), heading + "\n\n" + "\n\n".join(plain)
