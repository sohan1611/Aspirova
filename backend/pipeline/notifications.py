"""Notification worker logic (Doc 03 sec 4.3, Doc 02 sec 3.6, Doc
handoffs/PHASE-2-HANDOFF.md sec 5). Three independent jobs:

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
- send_closing_soon_alerts(): one grouped email per opted-in user for
  their bookmarked active opportunities closing within the configured
  deadline window, with per-opportunity notification-log deduplication.

All three enforce their caps via the notifications table (Doc 03 sec 4.3's
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
from html import escape

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from api.filters import exclude_stale_opportunities, student_rank_expression
from core import models
from core.config import get_settings
from core.email_client import send_email
from core.email_templates import email_layout, text_footer
from core.gating import can


def wants(user: models.User, key: str) -> bool:
    prefs = user.notification_prefs
    return not isinstance(prefs, dict) or prefs.get(key) is not False


logger = logging.getLogger(__name__)

DIGEST_FREQUENCY_CAP = timedelta(hours=20)
INSTANT_ALERT_LOOKBACK = timedelta(hours=3)
DIGEST_GENERIC_SAMPLE_SIZE = 5
DIGEST_RANKED_COMPANY_RESERVE_SIZE = 2


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


def _already_alerted(
    session: Session,
    user_id,
    opportunity_id: int,
    notification_type: str = "instant_alert",
) -> bool:
    return (
        session.scalar(
            select(models.Notification.id)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.opportunity_id == opportunity_id,
                models.Notification.type == notification_type,
                models.Notification.status == "sent",
            )
            .limit(1)
        )
        is not None
    )


def _dream_company_opportunities(
    session: Session, user_id, since: datetime, now: datetime
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
                exclude_stale_opportunities(now),
            )
            .order_by(models.Opportunity.first_seen_at.desc())
        ).all()
    )


def _generic_recent_opportunities(
    session: Session, since: datetime, limit: int, now: datetime
) -> list[models.Opportunity]:
    if limit <= 0:
        return []

    student_rank = student_rank_expression()
    ranking_order = [
        student_rank.asc(),
        models.Company.prestige_rank.asc().nullslast(),
        models.Opportunity.first_seen_at.desc(),
        models.Opportunity.id.desc(),
    ]
    ranked_opportunities = (
        select(
            models.Opportunity,
            student_rank.label("student_rank"),
            models.Company.prestige_rank.label("prestige_rank"),
            func.row_number()
            .over(
                partition_by=models.Opportunity.company_id,
                order_by=ranking_order,
            )
            .label("company_row_number"),
        )
        .outerjoin(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.first_seen_at >= since,
            exclude_stale_opportunities(now),
            models.Opportunity.category.in_(["internship", "job"]),
            student_rank < 2,
        )
        .subquery()
    )
    opportunity = aliased(models.Opportunity, ranked_opportunities)

    ranked_company_opportunities = list(
        session.scalars(
            select(opportunity)
            .where(
                ranked_opportunities.c.company_row_number == 1,
                ranked_opportunities.c.prestige_rank.is_not(None),
            )
            .order_by(
                ranked_opportunities.c.prestige_rank.asc(),
                ranked_opportunities.c.student_rank.asc(),
                ranked_opportunities.c.first_seen_at.desc(),
                ranked_opportunities.c.id.desc(),
            )
            .limit(min(DIGEST_RANKED_COMPANY_RESERVE_SIZE, limit))
        ).all()
    )

    reserved_company_ids = [
        opportunity.company_id
        for opportunity in ranked_company_opportunities
        if opportunity.company_id is not None
    ]
    remaining_limit = limit - len(ranked_company_opportunities)
    fill_opportunities: list[models.Opportunity] = []
    if remaining_limit > 0:
        fill_filters = [ranked_opportunities.c.company_row_number == 1]
        if reserved_company_ids:
            fill_filters.append(
                or_(
                    ranked_opportunities.c.company_id.is_(None),
                    ranked_opportunities.c.company_id.not_in(reserved_company_ids),
                )
            )
        fill_opportunities = list(
            session.scalars(
                select(opportunity)
                .where(*fill_filters)
                .order_by(
                    ranked_opportunities.c.student_rank.asc(),
                    ranked_opportunities.c.prestige_rank.asc().nullslast(),
                    ranked_opportunities.c.first_seen_at.desc(),
                    ranked_opportunities.c.id.desc(),
                )
                .limit(remaining_limit)
            ).all()
        )

    selected_ids = [
        opportunity.id for opportunity in [*ranked_company_opportunities, *fill_opportunities]
    ]
    if not selected_ids:
        return []

    return list(
        session.scalars(
            select(opportunity)
            .where(
                ranked_opportunities.c.company_row_number == 1,
                ranked_opportunities.c.id.in_(selected_ids),
            )
            .order_by(
                ranked_opportunities.c.student_rank.asc(),
                ranked_opportunities.c.prestige_rank.asc().nullslast(),
                ranked_opportunities.c.first_seen_at.desc(),
                ranked_opportunities.c.id.desc(),
            )
            .limit(limit)
        ).all()
    )


def _company_name(opportunity: models.Opportunity) -> str:
    return opportunity.company.name if opportunity.company else "Unknown"


def _render_digest(opportunities: list[models.Opportunity]) -> tuple[str, str]:
    lines = [f"- {o.title} at {_company_name(o)}: {o.apply_url}" for o in opportunities]
    text = (
        "Fresh opportunities matched to your interests — take a look while they're still open.\n\n"
        + "\n".join(lines)
        + "\n\n"
        + text_footer()
    )
    html_rows = "".join(
        (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border:1px solid #e7e0d4;border-collapse:separate;border-radius:8px;'
            'border-spacing:0;margin:0 0 12px;width:100%">'
            '<tr><td style="padding:16px">'
            "<p style=\"color:#2b2620;font-family:Georgia,'Times New Roman',serif;font-size:17px;"
            'font-weight:700;line-height:23px;margin:0 0 4px">'
            f"{escape(opportunity.title, quote=True)}</p>"
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'line-height:20px;margin:0 0 10px">'
            f"at {escape(_company_name(opportunity), quote=True)}</p>"
            f'<a href="{escape(opportunity.apply_url, quote=True)}" '
            'style="color:#5e2b47;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'font-weight:700;text-decoration:underline">View &amp; apply &rarr;</a>'
            "</td></tr></table>"
        )
        for opportunity in opportunities
    )
    html = email_layout(
        title="Your daily opportunity digest",
        intro_html=(
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
            'line-height:22px;margin:0 0 20px">Fresh opportunities matched to your interests — '
            "take a look while they're still open.</p>"
        ),
        body_html=html_rows,
        cta_label="Browse all opportunities",
        cta_url=get_settings().site_url,
    )
    return html, text


def _render_instant_alert(opportunity: models.Opportunity) -> tuple[str, str]:
    company_name = _company_name(opportunity)
    text = (
        "A role just opened at a company you're tracking.\n\n"
        f"{opportunity.title} at {company_name} was just posted.\n"
        f"View & apply: {opportunity.apply_url}\n\n" + text_footer()
    )
    body_html = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#faf7f0;border:1px solid #e7e0d4;border-collapse:separate;'
        'border-radius:8px;border-spacing:0;width:100%">'
        '<tr><td style="padding:20px">'
        '<p style="color:#5e2b47;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        "font-weight:700;letter-spacing:0.5px;line-height:16px;margin:0 0 8px;"
        'text-transform:uppercase">'
        "Just posted</p>"
        "<p style=\"color:#2b2620;font-family:Georgia,'Times New Roman',serif;font-size:20px;"
        'font-weight:700;line-height:27px;margin:0 0 6px">'
        f"{escape(opportunity.title, quote=True)}</p>"
        '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
        'line-height:22px;margin:0">'
        f"at {escape(company_name, quote=True)}</p>"
        "</td></tr></table>"
    )
    html = email_layout(
        title="A new opportunity is waiting",
        intro_html=(
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
            'line-height:22px;margin:0 0 20px">A role just opened at a company '
            "you're tracking.</p>"
        ),
        body_html=body_html,
        cta_label="View & apply",
        cta_url=opportunity.apply_url,
    )
    return html, text


def _render_closing_soon(
    opportunities: list[models.Opportunity],
    now: datetime,
) -> tuple[str, str]:
    if len(opportunities) == 1:
        opportunity = opportunities[0]
        assert opportunity.deadline is not None
        days_remaining = (opportunity.deadline.date() - now.date()).days
        if days_remaining <= 0:
            timing = "today"
        elif days_remaining == 1:
            timing = "tomorrow"
        else:
            timing = f"in {days_remaining} days"
        subject = f"'{opportunity.title}' closes {timing}"
    else:
        subject = f"{len(opportunities)} opportunities closing soon"

    html_rows = "".join(
        (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border:1px solid #e7e0d4;border-collapse:separate;border-radius:8px;'
            'border-spacing:0;margin:0 0 12px;width:100%">'
            '<tr><td style="padding:16px">'
            "<p style=\"color:#2b2620;font-family:Georgia,'Times New Roman',serif;font-size:17px;"
            'font-weight:700;line-height:23px;margin:0 0 6px">'
            f"{escape(opportunity.title, quote=True)}</p>"
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'line-height:20px;margin:0 0 10px">'
            f"Deadline: {escape(opportunity.deadline.strftime('%d %b %Y'), quote=True)}</p>"
            f'<a href="{escape(opportunity.apply_url, quote=True)}" '
            'style="color:#5e2b47;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'font-weight:700;text-decoration:underline">View &amp; apply &rarr;</a>'
            "</td></tr></table>"
        )
        for opportunity in opportunities
        if opportunity.deadline is not None
    )
    body_html = (
        html_rows + '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'line-height:20px;margin:8px 0 0">Deadlines can change. Please verify them at the '
        "linked source.</p>"
    )
    html = email_layout(
        title="Opportunities closing soon",
        intro_html=(
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
            'line-height:22px;margin:0 0 20px">A quick reminder to review your saved '
            "opportunities before their deadlines pass.</p>"
        ),
        body_html=body_html,
        cta_label="Review your saved opportunities",
        cta_url=f"{get_settings().site_url.rstrip('/')}/saved",
    )
    return subject, html


def _render_closing_soon_text(opportunities: list[models.Opportunity]) -> str:
    lines = [
        f"- {opportunity.title} — deadline {opportunity.deadline.strftime('%d %b %Y')}: "
        f"{opportunity.apply_url}"
        for opportunity in opportunities
        if opportunity.deadline is not None
    ]
    return (
        "Your bookmarked opportunities are closing soon:\n\n"
        + "\n".join(lines)
        + "\n\nDeadlines can change. Please verify them at the linked source.\n\n"
        + text_footer()
    )


def send_daily_digests(session: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    cap_since = now - DIGEST_FREQUENCY_CAP

    result = {"sent": 0, "failed": 0, "skipped_capped": 0, "skipped_empty": 0}

    for user in session.scalars(select(models.User)).all():
        try:
            if not can(session, user, "daily_digest"):
                continue
            if not wants(user, "daily_digest"):
                continue
            if _already_sent_recently(session, user.id, "digest", cap_since):
                result["skipped_capped"] += 1
                continue

            opportunities = _dream_company_opportunities(session, user.id, since, now)
            opportunities = [
                o for o in opportunities if not _already_alerted(session, user.id, o.id)
            ]
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
                    for o in _generic_recent_opportunities(
                        session, since, DIGEST_GENERIC_SAMPLE_SIZE, now
                    )
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
        except Exception:
            session.rollback()
            logger.exception("daily digest failed for user %s", user.id)
            result["failed"] += 1
            continue

    return result


def send_instant_alerts(session: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - INSTANT_ALERT_LOOKBACK

    result = {"sent": 0, "failed": 0, "skipped_not_eligible": 0, "skipped_already_alerted": 0}

    matches = session.execute(
        select(models.DreamCompany.user_id, models.Opportunity)
        .join(models.Opportunity, models.Opportunity.company_id == models.DreamCompany.company_id)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.first_seen_at >= since,
            exclude_stale_opportunities(now),
        )
    ).all()

    for user_id, opportunity in matches:
        try:
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
        except Exception:
            session.rollback()
            logger.exception("instant alert failed for user %s", user_id)
            result["failed"] += 1
            continue

    return result


def send_closing_soon_alerts(
    session: Session, *, now: datetime | None = None, within_days: int = 3
) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now + timedelta(days=within_days)
    result = {"users_notified": 0, "opportunities": 0, "failed": 0}

    for user in session.scalars(select(models.User)).all():
        try:
            if not wants(user, "closing_soon"):
                continue

            opportunities = list(
                session.scalars(
                    select(models.Opportunity)
                    .join(
                        models.Bookmark,
                        models.Bookmark.opportunity_id == models.Opportunity.id,
                    )
                    .where(
                        models.Bookmark.user_id == user.id,
                        models.Opportunity.status == "active",
                        exclude_stale_opportunities(now),
                        models.Opportunity.deadline.is_not(None),
                        models.Opportunity.deadline.between(now, cutoff),
                    )
                    .order_by(models.Opportunity.deadline.asc(), models.Opportunity.id.asc())
                ).all()
            )
            opportunities = [
                opportunity
                for opportunity in opportunities
                if not _already_alerted(
                    session,
                    user.id,
                    opportunity.id,
                    notification_type="closing_soon",
                )
            ]
            if not opportunities:
                continue

            subject, html = _render_closing_soon(opportunities, now)
            text = _render_closing_soon_text(opportunities)
            sent = send_email(user.email, subject, html, text)
            status = "sent" if sent else "failed"
            for opportunity in opportunities:
                _record_notification(
                    session,
                    user.id,
                    "closing_soon",
                    opportunity_id=opportunity.id,
                    status=status,
                )

            if sent:
                result["users_notified"] += 1
                result["opportunities"] += len(opportunities)
            else:
                result["failed"] += 1
        except Exception:
            session.rollback()
            logger.exception("closing-soon alert failed for user %s", user.id)
            result["failed"] += 1
            continue

    return result
