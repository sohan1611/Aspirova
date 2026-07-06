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
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from core import ai_budget, ai_client, email_client, models
from core.config import get_settings
from core.gating import can

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


def _company_name(opportunity: models.Opportunity) -> str:
    return opportunity.company.name if opportunity.company else "Unknown organization"


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
                models.Opportunity.status == "active",
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
                models.Opportunity.is_hidden.is_(True),
                models.Opportunity.first_seen_at >= since,
                models.Opportunity.first_seen_at <= now,
            )
            .order_by(models.Opportunity.first_seen_at.desc(), models.Opportunity.id.desc())
            .limit(REPORT_SECTION_LIMIT)
        ).unique()
    )


def _deadline_note(opportunity: models.Opportunity) -> str:
    if opportunity.deadline is None:
        return ""
    date = opportunity.deadline.strftime("%d %b %Y")
    if opportunity.deadline_confidence == "inferred":
        return f"Estimated deadline: {date}"
    if opportunity.deadline_confidence == "unknown":
        return f"Deadline (verify at source): {date}"
    return f"Deadline: {date}"


def _render_text_section(
    heading: str,
    opportunities: list[models.Opportunity],
    empty_message: str,
    *,
    include_deadline: bool = False,
) -> str:
    lines = [heading]
    if not opportunities:
        lines.append(empty_message)
        return "\n".join(lines)

    for opportunity in opportunities:
        detail = f" — {_deadline_note(opportunity)}" if include_deadline else ""
        lines.append(
            f"- {opportunity.title} at {_company_name(opportunity)}{detail}\n"
            f"  Source: {opportunity.apply_url}"
        )
    return "\n".join(lines)


def _render_html_section(
    heading: str,
    opportunities: list[models.Opportunity],
    empty_message: str,
    *,
    include_deadline: bool = False,
) -> str:
    if not opportunities:
        body = f'<p style="color:#475569;margin:8px 0 0">{escape(empty_message)}</p>'
    else:
        items: list[str] = []
        for opportunity in opportunities:
            deadline = ""
            if include_deadline:
                deadline = (
                    '<br><span style="color:#475569;font-size:14px">'
                    f"{escape(_deadline_note(opportunity))}</span>"
                )
            items.append(
                '<li style="margin:0 0 14px">'
                f"<strong>{escape(opportunity.title)}</strong> at "
                f"{escape(_company_name(opportunity))}{deadline}<br>"
                f'<a href="{escape(opportunity.apply_url, quote=True)}" '
                'style="color:#2563eb">View at source</a>'
                "</li>"
            )
        body = f'<ul style="padding-left:22px;margin:10px 0 0">{"".join(items)}</ul>'

    return (
        '<section style="border-top:1px solid #e2e8f0;padding:20px 0">'
        f'<h2 style="font-size:18px;color:#0f172a;margin:0">{escape(heading)}</h2>'
        f"{body}</section>"
    )


def _render_weekly_report(user: models.User, data: WeeklyReportData) -> tuple[str, str]:
    """Render a source-linked report without generating any body content."""
    greeting_name = (user.display_name or "").strip() or "there"
    text_parts = [
        "Your Aspirova weekly career report",
        f"Hi {greeting_name},",
    ]
    html_intro = ""
    if data.intro:
        text_parts.append(f"AI-assisted overview: {data.intro}")
        html_intro = (
            '<p style="background:#eff6ff;border-radius:10px;color:#1e3a8a;'
            'padding:14px 16px"><strong>AI-assisted overview:</strong> '
            f"{escape(data.intro)}</p>"
        )

    text_parts.extend(
        [
            _render_text_section(
                "Dream-company matches",
                data.dream_company_matches,
                "No new dream-company matches this week.",
            ),
            _render_text_section(
                "Closing soon",
                data.closing_soon,
                "No tracked opportunities close in the next seven days.",
                include_deadline=True,
            ),
            _render_text_section(
                "New hidden opportunities",
                data.hidden_opportunities,
                "No new hidden opportunities this week.",
            ),
            "Opportunity details can change. Always verify them at the linked source.",
        ]
    )
    text = "\n\n".join(text_parts)

    html_sections = "".join(
        [
            _render_html_section(
                "Dream-company matches",
                data.dream_company_matches,
                "No new dream-company matches this week.",
            ),
            _render_html_section(
                "Closing soon",
                data.closing_soon,
                "No tracked opportunities close in the next seven days.",
                include_deadline=True,
            ),
            _render_html_section(
                "New hidden opportunities",
                data.hidden_opportunities,
                "No new hidden opportunities this week.",
            ),
        ]
    )
    html = (
        '<div style="background:#f8fafc;padding:24px;font-family:Arial,sans-serif;'
        'color:#0f172a">'
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;'
        'margin:0 auto;max-width:640px;padding:28px">'
        '<p style="color:#2563eb;font-size:14px;font-weight:700;letter-spacing:.04em;'
        'margin:0 0 8px">ASPIROVA</p>'
        '<h1 style="font-size:26px;margin:0 0 18px">Your weekly career report</h1>'
        f'<p style="margin:0 0 18px">Hi {escape(greeting_name)},</p>'
        f"{html_intro}{html_sections}"
        '<p style="color:#64748b;font-size:12px;margin:18px 0 0">Opportunity details can '
        "change. Always verify them at the linked source.</p>"
        "</div></div>"
    )
    return html, text


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
        data = WeeklyReportData(
            dream_company_matches=_recent_dream_company_matches(session, user.id, since, current),
            closing_soon=closing_soon,
            hidden_opportunities=hidden_opportunities,
            intro=_cohort_intro(
                session,
                cohort=WEEKLY_REPORT_COHORT,
                cache=intro_cache,
                now=current,
            ),
        )
        html, text = _render_weekly_report(user, data)
        sent = email_client.send_email(
            user.email,
            "Your Aspirova weekly career report",
            html,
            text,
        )
        _record_delivery(session, user, data, now=current, sent=sent)
        result["sent" if sent else "failed"] += 1

    return result
