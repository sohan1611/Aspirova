"""Notification worker logic (Doc 03 sec 4.3, Doc 02 sec 3.6, Doc
handoffs/PHASE-2-HANDOFF.md sec 5). Two independent jobs:

- send_daily_digests(): one email per user per ~24h (Doc 02 sec 3.6: "one
  daily digest email per free user, not per-opportunity"), rule-based
  content (no AI/personalization until Phase 3) - opportunities from the
  user's dream companies if they have any, else a generic recent-
  opportunities sample, always excluding anything already covered by an
  instant alert to that same user.
- send_instant_alerts(): near-real-time, Pro/Pro-Lite only
  (plans.features.instant_alerts), one email per NEW opportunity matching
  a user's dream company - triggered by a lookback window on
  opportunities.first_seen_at rather than threading opportunity IDs
  through crawlers/runner.py's return value, so it keeps working
  correctly regardless of exactly when it runs relative to a crawl.

Both enforce their caps via the notifications table (Doc 03 sec 4.3's
(user_id, type, sent_at) index) - never a scattered ad-hoc check.

Deliberately a plain per-user loop, not a bulk-ops rewrite in the style of
pipeline/ingest.py's Part-2.4 refactor: that refactor was justified by a
measured, real bottleneck (a 25-minute crawl timeout at real scale). This
job has no such measured pressure yet at this project's current user
count - building for anticipated load here would violate the same
"scale by measured trigger" principle that justified the OTHER refactor
(Doc 02 sec 5, Doc 08 sec 1).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.email_client import send_email
from core.gating import can


def wants(user: models.User, key: str) -> bool:
    prefs = user.notification_prefs
    return not isinstance(prefs, dict) or prefs.get(key) is not False


logger = logging.getLogger(__name__)

DIGEST_FREQUENCY_CAP = timedelta(hours=20)
INSTANT_ALERT_LOOKBACK = timedelta(hours=3)
DIGEST_GENERIC_SAMPLE_SIZE = 5


def _record_notification(
    session: Session,
    user_id,
    notification_type: str,
    *,
    opportunity_id: int | None,
    status: str,
    meta: dict | None = None,
) -> None:
    session.add(
        models.Notification(
            user_id=user_id,
            type=notification_type,
            opportunity_id=opportunity_id,
            status=status,
            sent_at=datetime.now(timezone.utc) if status == "sent" else None,
            meta=meta,
        )
    )
    session.commit()


def _already_sent_recently(
    session: Session, user_id, notification_type: str, since: datetime
) -> bool:
    return (
        session.scalar(
            select(models.Notification.id)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.type == notification_type,
                models.Notification.status == "sent",
                models.Notification.sent_at >= since,
            )
            .limit(1)
        )
        is not None
    )


def _already_alerted(session: Session, user_id, opportunity_id: int) -> bool:
    return (
        session.scalar(
            select(models.Notification.id)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.opportunity_id == opportunity_id,
                models.Notification.type == "instant_alert",
                models.Notification.status == "sent",
            )
            .limit(1)
        )
        is not None
    )


def _dream_company_opportunities(
    session: Session, user_id, since: datetime
) -> list[models.Opportunity]:
    return list(
        session.scalars(
            select(models.Opportunity)
            .join(
                models.DreamCompany,
                models.DreamCompany.company_id == models.Opportunity.company_id,
            )
            .where(
                models.DreamCompany.user_id == user_id,
                models.Opportunity.status == "active",
                models.Opportunity.first_seen_at >= since,
            )
            .order_by(models.Opportunity.first_seen_at.desc())
        ).all()
    )


def _generic_recent_opportunities(
    session: Session, since: datetime, limit: int
) -> list[models.Opportunity]:
    return list(
        session.scalars(
            select(models.Opportunity)
            .where(models.Opportunity.status == "active", models.Opportunity.first_seen_at >= since)
            .order_by(models.Opportunity.first_seen_at.desc())
            .limit(limit)
        ).all()
    )


def _company_name(opportunity: models.Opportunity) -> str:
    return opportunity.company.name if opportunity.company else "Unknown"


def _render_digest(opportunities: list[models.Opportunity]) -> tuple[str, str]:
    lines = [f"- {o.title} at {_company_name(o)}: {o.apply_url}" for o in opportunities]
    text = "New opportunities for you:\n\n" + "\n".join(lines)
    html_items = "".join(
        f'<li><a href="{o.apply_url}">{o.title}</a> at {_company_name(o)}</li>'
        for o in opportunities
    )
    html = f"<p>New opportunities for you:</p><ul>{html_items}</ul>"
    return html, text


def _render_instant_alert(opportunity: models.Opportunity) -> tuple[str, str]:
    company_name = _company_name(opportunity)
    text = f"{opportunity.title} at {company_name} was just posted: {opportunity.apply_url}"
    html = (
        f"<p><strong>{opportunity.title}</strong> at {company_name} was just posted.</p>"
        f'<p><a href="{opportunity.apply_url}">Apply here</a></p>'
    )
    return html, text


def send_daily_digests(session: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    cap_since = now - DIGEST_FREQUENCY_CAP

    result = {"sent": 0, "failed": 0, "skipped_capped": 0, "skipped_empty": 0}

    for user in session.scalars(select(models.User)).all():
        if not can(session, user, "daily_digest"):
            continue
        if not wants(user, "daily_digest"):
            continue
        if _already_sent_recently(session, user.id, "digest", cap_since):
            result["skipped_capped"] += 1
            continue

        opportunities = _dream_company_opportunities(session, user.id, since)
        opportunities = [o for o in opportunities if not _already_alerted(session, user.id, o.id)]
        if not opportunities:
            # The generic fallback is a separate, unrelated query (all
            # recent active opportunities, not just dream-company ones) -
            # it must ALSO exclude already-alerted ones, or an opportunity
            # excluded above (because a Pro user's dream company already
            # got it as an instant alert) can leak right back in here,
            # since it's still a perfectly real, recent, active
            # opportunity as far as this second query is concerned.
            opportunities = [
                o
                for o in _generic_recent_opportunities(session, since, DIGEST_GENERIC_SAMPLE_SIZE)
                if not _already_alerted(session, user.id, o.id)
            ]
        if not opportunities:
            result["skipped_empty"] += 1
            continue

        html, text = _render_digest(opportunities)
        sent = send_email(user.email, "Your Aspirova daily digest", html, text)
        _record_notification(
            session,
            user.id,
            "digest",
            opportunity_id=None,
            status="sent" if sent else "failed",
            meta={"opportunity_ids": [o.id for o in opportunities]},
        )
        result["sent" if sent else "failed"] += 1

    return result


def send_instant_alerts(session: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - INSTANT_ALERT_LOOKBACK

    result = {"sent": 0, "failed": 0, "skipped_not_eligible": 0, "skipped_already_alerted": 0}

    matches = session.execute(
        select(models.DreamCompany.user_id, models.Opportunity)
        .join(models.Opportunity, models.Opportunity.company_id == models.DreamCompany.company_id)
        .where(models.Opportunity.status == "active", models.Opportunity.first_seen_at >= since)
    ).all()

    for user_id, opportunity in matches:
        user = session.get(models.User, user_id)
        if (
            user is None
            or not can(session, user, "instant_alerts")
            or not wants(user, "instant_alerts")
        ):
            result["skipped_not_eligible"] += 1
            continue
        if _already_alerted(session, user_id, opportunity.id):
            result["skipped_already_alerted"] += 1
            continue

        html, text = _render_instant_alert(opportunity)
        subject = f"New at {_company_name(opportunity)}: {opportunity.title}"
        sent = send_email(user.email, subject, html, text)
        _record_notification(
            session,
            user_id,
            "instant_alert",
            opportunity_id=opportunity.id,
            status="sent" if sent else "failed",
        )
        result["sent" if sent else "failed"] += 1

    return result
