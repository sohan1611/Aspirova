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
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased

from api.filters import (
    exclude_school_only_opportunities,
    exclude_stale_opportunities,
    student_rank_expression,
)
from core import models
from core.config import get_settings
from core.email_client import send_email
from core.email_templates import email_layout, text_footer
from core.gating import can
from core.organisers import REPUTED_ORGANISER_REGEX
from core.unsubscribe import list_unsubscribe_headers, unsubscribe_url


def wants(user: models.User, key: str) -> bool:
    prefs = user.notification_prefs
    return not isinstance(prefs, dict) or prefs.get(key) is not False


logger = logging.getLogger(__name__)

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


def _already_sent_today(session: Session, user_id, notification_type: str, now: datetime) -> bool:
    """Has this user already had this notification on the same UTC calendar day?

    Replaces a rolling frequency window for the daily digests, because a rolling
    window RATCHETS. Measured: a digest sent late at 15:12 UTC pushed a 20h cap
    to 11:12 the next day, so the morning run at 10:17 skipped all 11 users and
    nobody got that day's email at all. Each late send pushes the next one later
    or kills it outright.

    "At most once per calendar day" is what "daily digest" actually means, and it
    cannot ratchet: a late send today never suppresses tomorrow morning. It still
    makes the workflow's four cron entries safe, since a second firing on the
    same day is skipped exactly as before.
    """
    return (
        session.scalar(
            select(models.Notification.id)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.type == notification_type,
                models.Notification.status == "sent",
                func.date(models.Notification.sent_at) == now.date(),
            )
            .limit(1)
        )
        is not None
    )


def _sent_within(
    session: Session, user_id, notification_type: str, now: datetime, window: timedelta
) -> bool:
    """Did this user get `notification_type` inside the last `window`?

    Unlike _already_sent_today this IS a rolling window, deliberately: it asks
    "was the other email just now", which is a question about elapsed time, not
    about the calendar day. It cannot ratchet a daily send, because it only ever
    defers within the day - the calendar-day cap is still what decides whether
    the email happens at all.
    """
    return (
        session.scalar(
            select(models.Notification.id)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.type == notification_type,
                models.Notification.status == "sent",
                models.Notification.sent_at >= now - window,
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


def _render_digest(
    opportunities: list[models.Opportunity], unsub_url: str | None = None
) -> tuple[str, str]:
    lines = [f"- {o.title} at {_company_name(o)}: {o.apply_url}" for o in opportunities]
    text = (
        "Fresh opportunities matched to your interests — take a look while they're still open.\n\n"
        + "\n".join(lines)
        + "\n\n"
        + text_footer(unsub_url)
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
        unsubscribe_url=unsub_url,
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

    result = {"sent": 0, "failed": 0, "skipped_capped": 0, "skipped_empty": 0}

    for user in session.scalars(select(models.User)).all():
        try:
            if not can(session, user, "daily_digest"):
                continue
            if not wants(user, "daily_digest"):
                continue
            if _already_sent_today(session, user.id, "digest", now):
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

            html, text = _render_digest(opportunities, unsubscribe_url(user.id, "daily_digest"))
            sent = send_email(
                user.email,
                "Your Aspirova daily digest",
                html,
                text,
                headers=list_unsubscribe_headers(user.id, "daily_digest"),
            )
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


# ---------------------------------------------------------------------------
# Hackathon digest
#
# A separate daily email from send_daily_digests(). It exists because the
# generic digest ranks across the WHOLE corpus, and with ~24k jobs against ~740
# competitions a hackathon effectively never wins a slot - verified in
# production, where a digest of five internships went out while IIT Bhubaneswar
# and IIT Delhi hackathons sat active and unmentioned.
#
# Two rules distinguish it from the generic digest:
#   1. Only listings a reader can still ENTER. exclude_closed_competitions()
#      keeps a 14-day grace window, which is right for browsing (a page you can
#      still read) and wrong for an email telling you to go and apply.
#   2. At least HACKATHON_DIGEST_REPUTED_RESERVE slots are reserved for
#      top-tier organisers, so an inbox never fills with unknown college events
#      while an IIT hackathon closes unmentioned.
# ---------------------------------------------------------------------------

# Subject line, kept as a constant so it cannot drift from anything that refers
# to it later. Note the emoji is a deliberate founder choice: it slightly pushes
# Gmail toward the Promotions tab, which is the placement DMARC was just added to
# improve, so the two pull against each other a little.
HACKATHON_DIGEST_SUBJECT = "Your Daily Dose of Hackathons 🚀"

HACKATHON_DIGEST_SIZE = 5
HACKATHON_DIGEST_REPUTED_RESERVE = 2
HACKATHON_DIGEST_MAX_PER_SOURCE = 3

# Minimum runway for a listing to be worth emailing about. Sorting purely by
# soonest deadline looked right and was not: with ~760 live competitions, dozens
# expire every day, so every slot filled with something closing within hours -
# measured, the first five picks all closed the same day. A digest telling you
# about a hackathon you can no longer enter is worse than not sending one.
HACKATHON_DIGEST_MIN_LEAD = timedelta(days=2)

# The daily crawl lands around 07:00 UTC. Thirty-six hours tolerates one missed
# crawl but not two; measured stale Unstop rows last seen 2-3 days earlier were
# still being emailed with countdowns after the source had stopped listing them.
HACKATHON_DIGEST_MAX_STALENESS = timedelta(hours=36)

# Minimum spacing between a user's daily digest and their hackathon digest.
#
# These began life as two consecutive steps of one workflow, so they arrived
# about a minute apart - two emails from the same sender landing together, which
# reads as a burst and is the shape recipients unsubscribe from (and Gmail
# groups). Scheduling alone cannot guarantee the gap here: GitHub's cron is
# best-effort and drifts by hours on this repo, so a late daily run can land on
# top of an on-time hackathon run.
#
# So the gap is enforced per user at send time, and the two workflows are merely
# scheduled apart. A user inside the window is skipped, not dropped: the
# hackathon workflow has several cron slots through the day and a later one
# sends, still bounded by the once-per-calendar-day cap.
HACKATHON_DIGEST_MIN_GAP = timedelta(hours=2)

# Aspirova's audience is college students. Unstop carries school-level quizzes
# ("The Pi Quiz Juniors: 6th to 8th") that are real, active and entirely wrong
# for this list. Matches an explicit grade range or an explicit school framing -
# deliberately narrow, because a false positive silently drops a real event.
_SCHOOL_LEVEL_REGEX = (
    r"[0-9]+(st|nd|rd|th)[[:space:]]+to[[:space:]]+[0-9]+(st|nd|rd|th)"
    r"|(^|[^a-z])(class|classes|grade|grades)[[:space:]]+[0-9]"
    r"|school[[:space:]]+students"
)


@dataclass(frozen=True)
class _DigestCandidate:
    opportunity: models.Opportunity
    reputed: bool


def _reputed_organiser_expression():
    """1 for a top-tier organiser or a national-level event, else 0.

    Matches against title and organiser name together, because the signal lives
    in either one: "Agentic AI Hackathon" carries nothing, while its company
    "Indian Institute of Technology Bhubaneswar" does - and conversely
    "Brand Phoenix - National Level Marketing Challenge" carries it in the title.
    """
    haystack = func.concat(
        func.coalesce(models.Opportunity.title, ""),
        " ",
        func.coalesce(models.Company.name, ""),
    )
    return case((haystack.op("~*")(REPUTED_ORGANISER_REGEX), 1), else_=0)


def _hackathon_digest_opportunities(
    session: Session,
    now: datetime,
    limit: int = HACKATHON_DIGEST_SIZE,
) -> list[models.Opportunity]:
    """Pick the day's hackathons across deadlines, organisers and sources.

    Deliberately NOT ranked purely by reputation. Sorting everything by tier
    would bury a hackathon closing tomorrow behind a well-branded one closing in
    a month, and a digest exists to catch deadlines. Reserving slots gets both.
    """
    reputed = _reputed_organiser_expression()

    base_filters = [
        models.Opportunity.status == "active",
        models.Opportunity.is_hidden.is_not(True),
        models.Opportunity.category.in_(["hackathon", "competition"]),
        exclude_stale_opportunities(now),
        models.Opportunity.last_seen_at >= now - HACKATHON_DIGEST_MAX_STALENESS,
        # A printed countdown needs an explicit source date. No-deadline rows are
        # still allowed, because they render honestly as "no stated deadline".
        or_(
            models.Opportunity.deadline.is_(None),
            models.Opportunity.deadline_confidence == "explicit",
        ),
        # Stricter than exclude_closed_competitions(): that keeps a 14-day grace
        # so a closed page stays readable. An email must only carry things the
        # reader can still enter, with enough runway to act.
        or_(
            models.Opportunity.deadline.is_(None),
            models.Opportunity.deadline >= now + HACKATHON_DIGEST_MIN_LEAD,
        ),
        exclude_school_only_opportunities(),
        func.coalesce(models.Opportunity.title, "").op("!~*")(_SCHOOL_LEVEL_REGEX),
    ]

    # One per organiser, so a single institution posting five events cannot take
    # the whole digest - the same reasoning as the generic digest's per-company
    # row_number, and the reason /competitions interleaves sources. Rows with no
    # company partition on their own negated id, so each stays its own group
    # instead of every orphan collapsing into one bucket under NULL.

    ranked = (
        select(
            models.Opportunity.id.label("id"),
            reputed.label("reputed"),
            models.Opportunity.deadline.label("deadline"),
            models.Opportunity.first_seen_at.label("first_seen_at"),
            models.Opportunity.primary_source.label("primary_source"),
            func.row_number()
            .over(
                partition_by=func.coalesce(models.Opportunity.company_id, -models.Opportunity.id),
                order_by=[
                    reputed.desc(),
                    models.Opportunity.deadline.asc().nullslast(),
                    models.Opportunity.first_seen_at.desc(),
                    models.Opportunity.id.desc(),
                ],
            )
            .label("organiser_row"),
        )
        .select_from(models.Opportunity)
        .outerjoin(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(*base_filters)
        .subquery()
    )

    def _fetch(
        where_extra: list,
        order_by: list,
        count: int | None = None,
    ) -> list[_DigestCandidate]:
        if count is not None and count <= 0:
            return []
        query = (
            select(ranked.c.id, ranked.c.reputed)
            .where(ranked.c.organiser_row == 1, *where_extra)
            .order_by(*order_by)
        )
        if count is not None:
            query = query.limit(count)
        rows = session.execute(query).all()
        ids = [row.id for row in rows]
        if not ids:
            return []
        reputed_by_id = {row.id: bool(row.reputed) for row in rows}
        found = session.scalars(
            select(models.Opportunity).where(models.Opportunity.id.in_(ids))
        ).all()
        by_id = {opportunity.id: opportunity for opportunity in found}
        return [_DigestCandidate(by_id[i], reputed_by_id[i]) for i in ids if i in by_id]

    def _deadline_day(opportunity: models.Opportunity) -> int | None:
        if opportunity.deadline is None:
            return None
        deadline = opportunity.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return (deadline - now).days

    def _source_key(candidate: _DigestCandidate) -> str:
        return candidate.opportunity.primary_source or "__unknown__"

    def _candidate_day(candidate: _DigestCandidate) -> int | None:
        return _deadline_day(candidate.opportunity)

    def _day_sort_key(day: int | None) -> tuple[int, int]:
        return (1, 0) if day is None else (0, day)

    def _ordered_days(candidates: list[_DigestCandidate]) -> list[int | None]:
        return sorted({_candidate_day(candidate) for candidate in candidates}, key=_day_sort_key)

    def _spread_days(candidates: list[_DigestCandidate], count: int) -> list[int | None]:
        """Choose deadline buckets across the whole range, not the next N days.

        The first deadline-diversity fix walked candidates already ordered by
        urgency. With ~440 eligible rows spanning every upcoming day, that made
        the digest read as 2, 3, 4, 5, 6 days - as machine-made as five same-day
        deadlines. Anchor on the closest real deadline, then sample the full
        available range so the remaining buckets have visible breathing room.
        """
        if count <= 0:
            return []

        days = _ordered_days(candidates)
        dated_days = [day for day in days if day is not None]
        selected: list[int | None] = []
        if dated_days:
            target = min(count, len(dated_days))
            indexes = (
                [0]
                if target == 1
                else [round(i * (len(dated_days) - 1) / (target - 1)) for i in range(target)]
            )
            for index in indexes:
                day = dated_days[index]
                if day not in selected:
                    selected.append(day)
            for day in dated_days:
                if len(selected) >= target:
                    break
                if day not in selected:
                    selected.append(day)

        if len(selected) < count and None in days:
            selected.append(None)
        return selected

    def _deadline_diverse_selection(candidates: list[_DigestCandidate]) -> list[models.Opportunity]:
        """Select digest rows with distinct deadline-days before any repeat fill."""
        cap = min(limit, len(candidates))
        if cap <= 0:
            return []

        buckets: dict[int | None, list[_DigestCandidate]] = defaultdict(list)
        for candidate in candidates:
            buckets[_candidate_day(candidate)].append(candidate)

        day_order = _spread_days(candidates, cap)
        day_order.extend(day for day in _ordered_days(candidates) if day not in day_order)
        distinct_day_count = len(buckets)

        source_totals = Counter(_source_key(candidate) for candidate in candidates)
        dominant_source = None
        required_other_source_slots = 0
        if len(source_totals) > 1:
            dominant_source = max(source_totals, key=lambda source: (source_totals[source], source))
            other_source_candidates = sum(
                count for source, count in source_totals.items() if source != dominant_source
            )
            required_other_source_slots = min(2, cap, other_source_candidates)

        selected: list[_DigestCandidate] = []
        selected_ids: set[int] = set()
        selected_days: set[int | None] = set()
        selected_source_counts: Counter[str] = Counter()

        def _source_allowed(
            candidate: _DigestCandidate,
            *,
            enforce_source: bool,
            protect_other_sources: bool,
        ) -> bool:
            if not enforce_source:
                return True

            source = _source_key(candidate)
            if selected_source_counts[source] >= HACKATHON_DIGEST_MAX_PER_SOURCE:
                return False

            if protect_other_sources and dominant_source is not None and source == dominant_source:
                other_selected = len(selected) - selected_source_counts[dominant_source]
                remaining_after_pick = cap - (len(selected) + 1)
                if other_selected + remaining_after_pick < required_other_source_slots:
                    return False

            return True

        def _best_candidate(
            candidates_to_scan: list[_DigestCandidate],
            *,
            unique_days: bool,
            enforce_source: bool,
            protect_other_sources: bool,
            require_reputed: bool = False,
        ) -> _DigestCandidate | None:
            for candidate in candidates_to_scan:
                opportunity = candidate.opportunity
                if opportunity.id in selected_ids:
                    continue
                if require_reputed and not candidate.reputed:
                    continue
                day = _candidate_day(candidate)
                if unique_days and day in selected_days:
                    continue
                if not _source_allowed(
                    candidate,
                    enforce_source=enforce_source,
                    protect_other_sources=protect_other_sources,
                ):
                    continue
                return candidate
            return None

        def _add(candidate: _DigestCandidate) -> None:
            selected.append(candidate)
            selected_ids.add(candidate.opportunity.id)
            selected_days.add(_candidate_day(candidate))
            selected_source_counts[_source_key(candidate)] += 1

        def _fill_unique_days(*, enforce_source: bool, protect_other_sources: bool) -> None:
            for day in day_order:
                if len(selected) >= cap:
                    break
                if day in selected_days:
                    continue
                candidate = _best_candidate(
                    buckets[day],
                    unique_days=True,
                    enforce_source=enforce_source,
                    protect_other_sources=protect_other_sources,
                )
                if candidate is not None:
                    _add(candidate)

        def _fill_repeated_days(*, enforce_source: bool) -> None:
            for candidate in candidates:
                if len(selected) >= cap:
                    break
                if candidate.opportunity.id in selected_ids:
                    continue
                if not _source_allowed(
                    candidate,
                    enforce_source=enforce_source,
                    protect_other_sources=enforce_source,
                ):
                    continue
                _add(candidate)

        # Always spend the first logical slot on the closest deadline bucket.
        # The final email is shuffled later, so this affects inclusion, not
        # rendered order.
        if day_order:
            urgent = _best_candidate(
                buckets[day_order[0]],
                unique_days=True,
                enforce_source=True,
                protect_other_sources=False,
            )
            if urgent is not None:
                _add(urgent)

        # Reputed organisers get a reserve, but not at the cost of source
        # diversity. That complaint was measured separately: 360 Unstop rows vs
        # 79 other aggregator rows let Unstop sweep all five slots unless source
        # balance is protected before the reserve spends another dominant-source
        # pick.
        reputed_target = min(
            HACKATHON_DIGEST_REPUTED_RESERVE,
            cap,
            sum(1 for candidate in candidates if candidate.reputed),
        )
        while sum(1 for candidate in selected if candidate.reputed) < reputed_target:
            candidate = _best_candidate(
                candidates,
                unique_days=True,
                enforce_source=True,
                protect_other_sources=True,
                require_reputed=True,
            )
            if candidate is None:
                break
            _add(candidate)

        _fill_unique_days(enforce_source=True, protect_other_sources=True)
        if len(selected) < cap and distinct_day_count >= cap:
            # If source balance and deadline uniqueness conflict, keep the
            # no-two-deadline-days guarantee and relax source balance before
            # allowing repeated dates.
            _fill_unique_days(enforce_source=False, protect_other_sources=False)

        if len(selected) < cap and distinct_day_count < cap:
            # Existing deferred-repeat behaviour: only repeat a deadline-day
            # once the available distinct buckets genuinely cannot fill the
            # digest. Try the source cap first, then ship a full digest if the
            # dominant source is the only remaining way to fill the last slot.
            _fill_repeated_days(enforce_source=True)
            _fill_repeated_days(enforce_source=False)

        rng = random.Random(
            (now if now.tzinfo else now.replace(tzinfo=timezone.utc))
            .astimezone(timezone.utc)
            .date()
            .toordinal()
        )
        rng.shuffle(selected)
        if len({_candidate_day(candidate) for candidate in selected}) > 1 and [
            _candidate_day(candidate) for candidate in selected
        ] == sorted((_candidate_day(candidate) for candidate in selected), key=_day_sort_key):
            selected = selected[1:] + selected[:1]

        return [candidate.opportunity for candidate in selected]

    # Strongest first inside a chosen deadline-day bucket: reputed organiser,
    # then soonest deadline, newest first_seen_at, and finally highest id. The
    # bucket picker decides WHICH days appear; this order decides which row best
    # represents any chosen day.
    quality_order = [
        ranked.c.reputed.desc(),
        ranked.c.deadline.asc().nullslast(),
        ranked.c.first_seen_at.desc(),
        ranked.c.id.desc(),
    ]

    candidates = _fetch([], quality_order)
    return _deadline_diverse_selection(candidates)


def _render_hackathon_digest(
    opportunities: list[models.Opportunity], now: datetime, unsub_url: str | None = None
) -> tuple[str, str]:
    """Deadline is the headline here, unlike the generic digest.

    A job listing is browsable for weeks; a hackathon is a date. Showing days
    remaining is the single most useful thing this email can say.
    """

    def _closes_in(opportunity: models.Opportunity) -> str:
        if opportunity.deadline is None:
            return "no stated deadline"
        deadline = opportunity.deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        days = (deadline - now).days
        if days <= 0:
            return "closes today"
        if days == 1:
            return "closes tomorrow"
        return f"closes in {days} days"

    lines = [
        f"- {o.title} ({_company_name(o)}) - {_closes_in(o)}: {o.apply_url}" for o in opportunities
    ]
    text = (
        "Hackathons and competitions open right now - entries close on the dates below.\n\n"
        + "\n".join(lines)
        + "\n\n"
        + text_footer(unsub_url)
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
            'line-height:20px;margin:0 0 6px">'
            f"by {escape(_company_name(opportunity), quote=True)}</p>"
            '<p style="color:#8a4b2f;font-family:Arial,Helvetica,sans-serif;font-size:13px;'
            'font-weight:700;line-height:18px;margin:0 0 10px">'
            f"{escape(_closes_in(opportunity), quote=True)}</p>"
            f'<a href="{escape(opportunity.apply_url, quote=True)}" '
            'style="color:#5e2b47;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'font-weight:700;text-decoration:underline">View &amp; enter &rarr;</a>'
            "</td></tr></table>"
        )
        for opportunity in opportunities
    )

    html = email_layout(
        title="Hackathons open right now",
        intro_html=(
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
            'line-height:22px;margin:0 0 20px">Hackathons and competitions you can still '
            "enter, spread across upcoming deadlines.</p>"
        ),
        body_html=html_rows,
        cta_label="Browse all competitions",
        cta_url=f"{get_settings().site_url}/competitions",
        unsubscribe_url=unsub_url,
    )
    return html, text


def send_hackathon_digests(session: Session, *, now: datetime | None = None) -> dict:
    """One hackathon digest per user per ~24h.

    Entitlement reuses the free-tier daily_digest feature rather than adding a
    plan key: this is free for everyone by design, and a new key would need a
    plans migration to say the same thing. The opt-out is its own preference,
    so a reader can silence hackathons while keeping the daily digest.
    """
    now = now or datetime.now(timezone.utc)

    result = {
        "sent": 0,
        "failed": 0,
        "skipped_capped": 0,
        "skipped_empty": 0,
        "skipped_too_soon": 0,
    }

    opportunities = _hackathon_digest_opportunities(session, now)
    if not opportunities:
        # Nothing enterable today - send nobody an empty email.
        result["skipped_empty"] = len(list(session.scalars(select(models.User)).all()))
        return result

    # Selection stays hoisted - that is the query, and it is identical for
    # everyone. Rendering moves into the loop because the unsubscribe link is
    # per-recipient: one shared body would hand every reader the same token.
    opportunity_ids = [opportunity.id for opportunity in opportunities]

    for user in session.scalars(select(models.User)).all():
        try:
            if not can(session, user, "daily_digest"):
                continue
            if not wants(user, "hackathon_digest"):
                continue
            if _already_sent_today(session, user.id, "hackathon_digest", now):
                result["skipped_capped"] += 1
                continue
            # "digest" is the type the worker records for the daily digest -
            # see _notification_copy in api/notifications.py, where the legacy
            # name is kept readable alongside daily_digest.
            if _sent_within(
                session, user.id, "digest", now, HACKATHON_DIGEST_MIN_GAP
            ) or _sent_within(session, user.id, "daily_digest", now, HACKATHON_DIGEST_MIN_GAP):
                result["skipped_too_soon"] += 1
                continue

            html, text = _render_hackathon_digest(
                opportunities, now, unsubscribe_url(user.id, "hackathon_digest")
            )
            sent = send_email(
                user.email,
                HACKATHON_DIGEST_SUBJECT,
                html,
                text,
                headers=list_unsubscribe_headers(user.id, "hackathon_digest"),
            )
            _record_notification(
                session,
                user.id,
                "hackathon_digest",
                opportunity_id=None,
                status="sent" if sent else "failed",
                meta={"opportunity_ids": opportunity_ids},
            )
            result["sent" if sent else "failed"] += 1
        except Exception:
            session.rollback()
            logger.exception("hackathon digest failed for user %s", user.id)
            result["failed"] += 1
            continue

    return result
