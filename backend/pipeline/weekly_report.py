"""Offline weekly career-report assembly (Doc 05 sec 2.5).

The report body is entirely templated from stored opportunity data. The
only optional generation is one short introduction shared by every
eligible user in a worker run; blank AI configuration and exhausted AI
budget both degrade to the complete templated report.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api.filters import exclude_stale_opportunities, followed_company_match
from core import ai_budget, ai_client, models
from core.config import get_settings
from core.email_components import MUTED, TABLE, greeting, opportunity_card, section, status_panel
from core.email_templates import email_layout, text_footer
from core.gating import can
from core.unsubscribe import list_unsubscribe_headers, unsubscribe_url
from pipeline.notifications import send_email, wants

logger = logging.getLogger(__name__)

REPORT_LOOKBACK = timedelta(days=7)
CLOSING_SOON_WINDOW = timedelta(days=7)
REPORT_SECTION_LIMIT = 5
WEEKLY_REPORT_COHORT = "paid_students"


@dataclass(frozen=True, slots=True)
class WeeklyReportData:
    """Stored data assembled for one user's templated report."""

    dream_company_matches: list[models.Opportunity]
    closing_soon: list[models.Opportunity]
    hidden_opportunities: list[models.Opportunity]
    intro: str | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    current = _as_utc(now)
    week_start = (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return week_start, week_start + timedelta(days=7)


def _already_sent_this_week(session: Session, user_id: uuid.UUID, now: datetime) -> bool:
    week_start, week_end = _iso_week_bounds(now)
    return (
        session.scalar(
            select(models.Notification.id)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.type == "weekly_report",
                models.Notification.status == "sent",
                models.Notification.sent_at >= week_start,
                models.Notification.sent_at < week_end,
            )
            .limit(1)
        )
        is not None
    )


def _recent_dream_company_matches(
    session: Session, user_id: uuid.UUID, since: datetime, now: datetime
) -> list[models.Opportunity]:
    return list(
        session.scalars(
            select(models.Opportunity)
            .join(
                models.DreamCompany,
                models.DreamCompany.company_id == models.Opportunity.company_id,
            )
            .options(joinedload(models.Opportunity.company))
            .where(
                models.DreamCompany.user_id == user_id,
                followed_company_match(),
                models.Opportunity.status == "active",
                exclude_stale_opportunities(now),
                models.Opportunity.first_seen_at >= since,
                models.Opportunity.first_seen_at <= now,
            )
            .order_by(models.Opportunity.first_seen_at.desc(), models.Opportunity.id.desc())
            .limit(REPORT_SECTION_LIMIT)
        ).unique()
    )


def _closing_soon_opportunities(session: Session, now: datetime) -> list[models.Opportunity]:
    return list(
        session.scalars(
            select(models.Opportunity)
            .options(joinedload(models.Opportunity.company))
            .where(
                models.Opportunity.status == "active",
                exclude_stale_opportunities(now),
                models.Opportunity.deadline.is_not(None),
                models.Opportunity.deadline >= now,
                models.Opportunity.deadline <= now + CLOSING_SOON_WINDOW,
            )
            .order_by(models.Opportunity.deadline.asc(), models.Opportunity.id.asc())
            .limit(REPORT_SECTION_LIMIT)
        ).unique()
    )


def _recent_hidden_opportunities(
    session: Session, since: datetime, now: datetime
) -> list[models.Opportunity]:
    return list(
        session.scalars(
            select(models.Opportunity)
            .options(joinedload(models.Opportunity.company))
            .where(
                models.Opportunity.status == "active",
                exclude_stale_opportunities(now),
                models.Opportunity.is_hidden.is_(True),
                models.Opportunity.first_seen_at >= since,
                models.Opportunity.first_seen_at <= now,
            )
            .order_by(models.Opportunity.first_seen_at.desc(), models.Opportunity.id.desc())
            .limit(REPORT_SECTION_LIMIT)
        ).unique()
    )


def _render_weekly_report(
    user: models.User,
    data: WeeklyReportData,
    unsub_url: str | None = None,
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Render a source-linked report without generating any body content."""
    current = now or datetime.now(timezone.utc)
    sections = [
        (
            "Dream-company matches",
            data.dream_company_matches,
            "No new dream-company matches this week.",
        ),
        (
            "Closing soon",
            data.closing_soon,
            "No tracked opportunities close in the next seven days.",
        ),
    ]
    # Hidden opportunities are neither running nor sold (README 2026-11-03: Pro sells
    # only what runs), so an always-empty section would advertise a missing feature.
    # It appears again as soon as there is something in it.
    if data.hidden_opportunities:
        sections.append(
            (
                "New hidden opportunities",
                data.hidden_opportunities,
                "No new hidden opportunities this week.",
            )
        )
    count = sum(len(items) for _, items, _ in sections)
    summary = f"{count} {'pick' if count == 1 else 'picks'} for you this week"
    text_parts = ["Your Aspirova weekly career report", greeting(user.display_name), summary]
    html_parts = []
    if data.intro:
        text_parts.append(f"AI-assisted overview: {data.intro}")
        html_parts.append(status_panel("accent", ["AI-assisted overview:", data.intro]))
    for heading, items, empty_message in sections:
        cards = [
            opportunity_card(o, now=current, button_url=o.apply_url, deadline_policy="any")
            for o in items
        ]
        body = "".join(h for h, _ in cards)
        if not items:
            body = (
                f'<table {TABLE} width="100%" class="em-card" bgcolor="#ffffff" '
                'style="border:1px solid #e2e7f0;border-radius:8px;margin-bottom:12px">'
                f'<tr><td class="em-muted" style="color:{MUTED};padding:16px;font-size:14px;'
                f'line-height:20px">{empty_message}</td></tr></table>'
            )
        html_parts.append(section(heading, len(items), body))
        text_parts.append(heading + "\n\n" + ("\n\n".join(t for _, t in cards) or empty_message))
    note = "Opportunity details can change. Always verify them at the linked source."
    html_parts.append(
        f'<p class="em-muted" style="color:{MUTED};font-size:12px;line-height:18px">{note}</p>'
    )
    # N-09: state the rule behind each section, so every pick is reproducible.
    reason = (
        "You get this every week because the weekly career report is on. Dream-company "
        "matches are new roles at companies you follow; Closing soon lists listings you "
        "saved whose deadline is in the next 7 days. Change what you get under Manage "
        "email preferences."
    )
    text_parts.extend([note, reason, text_footer(unsub_url)])
    html = email_layout(
        title="Your weekly career report",
        kind_label="Weekly report",
        unsubscribe_url=unsub_url,
        greeting=greeting(user.display_name),
        summary=summary,
        preheader=summary,
        body_html="".join(html_parts),
        cta_label="Open Aspirova",
        cta_url=get_settings().site_url,
        footer_note=reason,
    )
    return html, "\n\n".join(text_parts)


def _cohort_intro(
    session: Session,
    *,
    cohort: str,
    cache: dict[str, str | None],
    now: datetime,
) -> str | None:
    """Return one run-cached intro shared by every member of a cohort."""
    if cohort in cache:
        return cache[cohort]

    # Cache the fallback first so a provider error can never trigger a
    # second generation attempt for another user in this run.
    cache[cohort] = None
    if not get_settings().anthropic_api_key or ai_budget.is_over_budget(session, now=now):
        return None

    try:
        result = ai_client.generate(
            session,
            feature="weekly_report.intro",
            system=(
                "Write concise, practical career guidance. Return one short paragraph only; "
                "do not invent or name opportunities."
            ),
            prompt=(
                "Write a general two-sentence introduction for this week's Aspirova career "
                "report for paid student users. Encourage prioritizing relevant matches and "
                "checking near deadlines."
            ),
        )
    except Exception:
        logger.warning("weekly report intro generation failed; using template only", exc_info=True)
        return None

    intro = " ".join(result.text.split()).strip()
    cache[cohort] = intro[:600].rstrip() or None
    return cache[cohort]


def _record_delivery(
    session: Session,
    user: models.User,
    data: WeeklyReportData,
    *,
    now: datetime,
    sent: bool,
) -> None:
    iso_year, iso_week, _weekday = now.isocalendar()
    session.add(
        models.Notification(
            user_id=user.id,
            type="weekly_report",
            opportunity_id=None,
            status="sent" if sent else "failed",
            sent_at=now if sent else None,
            meta={
                "iso_week": f"{iso_year}-W{iso_week:02d}",
                "dream_company_match_ids": [item.id for item in data.dream_company_matches],
                "closing_soon_ids": [item.id for item in data.closing_soon],
                "hidden_opportunity_ids": [item.id for item in data.hidden_opportunities],
                "intro_included": data.intro is not None,
            },
        )
    )
    session.commit()


def send_weekly_reports(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Build and send at most one report per eligible user per ISO week."""
    current = _as_utc(now or datetime.now(timezone.utc))
    result = {
        "sent": 0,
        "failed": 0,
        "skipped_ineligible": 0,
        "skipped_already_sent": 0,
    }

    recipients: list[models.User] = []
    for user in session.scalars(select(models.User)).all():
        if not can(session, user, "weekly_report"):
            result["skipped_ineligible"] += 1
            continue
        if not wants(user, "weekly_report"):
            result["skipped_ineligible"] += 1
            continue
        if _already_sent_this_week(session, user.id, current):
            result["skipped_already_sent"] += 1
            continue
        recipients.append(user)

    if not recipients:
        return result

    since = current - REPORT_LOOKBACK
    closing_soon = _closing_soon_opportunities(session, current)
    hidden_opportunities = _recent_hidden_opportunities(session, since, current)
    intro_cache: dict[str, str | None] = {}

    for user in recipients:
        try:
            data = WeeklyReportData(
                dream_company_matches=_recent_dream_company_matches(
                    session, user.id, since, current
                ),
                closing_soon=closing_soon,
                hidden_opportunities=hidden_opportunities,
                intro=_cohort_intro(
                    session,
                    cohort=WEEKLY_REPORT_COHORT,
                    cache=intro_cache,
                    now=current,
                ),
            )
            html, text = _render_weekly_report(
                user, data, unsub_url=unsubscribe_url(user.id, "weekly_report"), now=current
            )
            sent = send_email(
                user.email,
                "Your Aspirova weekly career report",
                html,
                text,
                headers=list_unsubscribe_headers(user.id, "weekly_report"),
            )
            _record_delivery(session, user, data, now=current, sent=sent)
            result["sent" if sent else "failed"] += 1
        except Exception:
            session.rollback()
            logger.exception("weekly report failed for user %s", user.id)
            result["failed"] += 1
            continue

    return result
