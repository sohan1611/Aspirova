"""Notification workers with deterministic company and domain matching.

Company alerts are grouped once per user per run: paid users receive them
following crawls and on daily runs; free users receive at most one per UTC
day. The daily digest excludes prior company alerts from its per-user
opportunity list and appends shared hackathon picks. Legacy hackathon opt-outs
suppress those picks. Each digest covers listings first seen since the
reader's previous digest, never repeats what their last week of digests
carried, and only carries listings that are still open; preview_daily_digest
renders the same selection without sending or recording it. Closing-soon reminders keep their own preference.
All entitlements use can(), and sent notification rows provide deduplication.
"""

import logging
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, aliased

from api.filters import (
    exclude_closed_competitions,
    exclude_experienced_only_opportunities,
    exclude_school_only_opportunities,
    exclude_stale_opportunities,
    followed_company_match,
    student_rank_expression,
)
from core import models
from core.config import get_settings
from core.email_components import (
    MUTED,
    _utc,
    greeting,
    grouped_cards,
    opportunity_card,
    section,
)
from core.email_templates import email_layout, text_footer
from core.gating import can
from core.organisers import REPUTED_ORGANISER_REGEX
from core.unsubscribe import list_unsubscribe_headers, unsubscribe_url
from pipeline.company_alert_email import CompanyAlertGroup, render_company_alert


def wants(user: models.User, key: str) -> bool:
    prefs = user.notification_prefs
    return not isinstance(prefs, dict) or prefs.get(key) is not False


logger = logging.getLogger(__name__)

COMPANY_ALERT_LOOKBACK = timedelta(hours=72)
DIGEST_GENERIC_SAMPLE_SIZE = 5
DIGEST_RANKED_COMPANY_RESERVE_SIZE = 2
DAILY_DIGEST_SUBJECT = "Your Aspirova daily digest"
HACKATHON_DIGEST_SUBJECT = "Your Daily Dose of Hackathons 🚀"
COMBINED_DIGEST_SUBJECT = "Your Aspirova daily digest + hackathons 🚀"

# Daily digest window and repeat guard (spec N-05).
#
# Each digest covers listings first seen since this reader's previous
# successful digest. A fixed "last 24 hours" window overlapped whenever the
# scheduler ran late one day and early the next (the cron fires anywhere from
# 04:47 to after 15:00 UTC), so the same listings went out twice; and a day the
# scheduler skipped entirely dropped that day's listings for good. The window
# is never longer than DIGEST_WINDOW_MAX, so a returning reader is not sent a
# week of backlog in one email.
DIGEST_WINDOW_DEFAULT = timedelta(hours=24)
DIGEST_WINDOW_MAX = timedelta(hours=72)
# Nothing that appeared in this reader's digest during the last week is sent to
# them again. For the hackathon picks this is the rule that matters: they are
# chosen per day from the same pool, so a strong listing otherwise reappears
# every morning until it closes.
DIGEST_REPEAT_LOOKBACK = timedelta(days=7)
_HACKATHON_CATEGORIES = {"hackathon", "competition"}


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


def _digest_open_filters(now: datetime) -> list:
    """An email may only carry listings the reader can still act on.

    status == "active" alone is not enough: a listing closed on absence keeps
    status "active" with closed_at set for its 14-day grace (pipeline/expire.py),
    and hidden rows are moderated out of every public surface.
    """
    return [
        models.Opportunity.is_hidden.is_not(True),
        models.Opportunity.closed_at.is_(None),
        or_(models.Opportunity.deadline.is_(None), models.Opportunity.deadline > now),
    ]


def _not_in(ids: frozenset[int]) -> list:
    return [models.Opportunity.id.not_in(sorted(ids))] if ids else []


@dataclass(frozen=True)
class DigestHistory:
    """This reader's successful digests inside DIGEST_REPEAT_LOOKBACK."""

    last_sent_at: datetime | None
    recent_ids: frozenset[int]


def _digest_history(session: Session, user_id, now: datetime) -> DigestHistory:
    rows = session.execute(
        select(models.Notification.sent_at, models.Notification.meta)
        .where(
            models.Notification.user_id == user_id,
            models.Notification.type == "digest",
            models.Notification.status == "sent",
            models.Notification.sent_at >= now - DIGEST_REPEAT_LOOKBACK,
        )
        .order_by(models.Notification.sent_at.desc())
    ).all()
    recent: set[int] = set()
    for row in rows:
        meta = row.meta if isinstance(row.meta, dict) else {}
        for key in ("opportunity_ids", "hackathon_ids"):
            values = meta.get(key)
            if isinstance(values, list):
                recent.update(value for value in values if isinstance(value, int))
    last_sent_at = _utc(rows[0].sent_at) if rows and rows[0].sent_at else None
    return DigestHistory(last_sent_at=last_sent_at, recent_ids=frozenset(recent))


def _digest_window_start(history: DigestHistory, now: datetime) -> datetime:
    if history.last_sent_at is None:
        return now - DIGEST_WINDOW_DEFAULT
    return max(history.last_sent_at, now - DIGEST_WINDOW_MAX)


def _dream_company_opportunities(
    session: Session,
    user_id,
    since: datetime,
    now: datetime,
    exclude_ids: frozenset[int] = frozenset(),
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
                followed_company_match(),
                models.Opportunity.status == "active",
                models.Opportunity.first_seen_at >= since,
                exclude_stale_opportunities(now),
                *_digest_open_filters(now),
                *_not_in(exclude_ids),
            )
            .order_by(models.Opportunity.first_seen_at.desc())
        ).all()
    )


def _generic_recent_opportunities(
    session: Session,
    since: datetime,
    limit: int,
    now: datetime,
    exclude_ids: frozenset[int] = frozenset(),
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
            *_digest_open_filters(now),
            *_not_in(exclude_ids),
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


def send_email(
    to: str, subject: str, html: str, text: str, headers: dict[str, str] | None = None
) -> bool:
    """Load the transport only on an actual send, keeping offline rendering pure."""
    from core.email_client import send_email as deliver

    return deliver(to, subject, html, text, headers=headers)


def _render_digest(
    opportunities: list[models.Opportunity],
    unsub_url: str | None = None,
    *,
    display_name: str | None = None,
    now: datetime | None = None,
    hackathons: list[models.Opportunity] | None = None,
) -> tuple[str, str]:
    current = now or datetime.now(timezone.utc)
    jobs = [o for o in opportunities if o.category not in _HACKATHON_CATEGORIES]
    events = [o for o in opportunities if o.category in _HACKATHON_CATEGORIES]
    existing_ids = {o.id for o in opportunities if o.id is not None}
    events.extend(o for o in (hackathons or []) if o.id is None or o.id not in existing_ids)
    job_count, event_count = len(jobs), len(events)
    opportunity_noun = "opportunity" if job_count == 1 else "opportunities"
    hackathon_noun = "hackathon" if event_count == 1 else "hackathons"
    if jobs and events:
        summary = (
            f"{job_count} new {opportunity_noun} and {event_count} {hackathon_noun} "
            "picked for you today"
        )
    elif events:
        event_noun = (
            "hackathon or competition" if event_count == 1 else "hackathons and competitions"
        )
        summary = f"{event_count} {event_noun} you can still enter"
    else:
        summary = f"{job_count} new {opportunity_noun} picked for you today"
    body, cards_text, first_card = grouped_cards(jobs, now=current)
    if events:
        cards = [
            opportunity_card(
                o,
                now=current,
                button_url=o.apply_url,
                button_label="View & Enter",
                deadline_policy="any",
            )
            for o in events
        ]
        body += section(
            "Hackathons & competitions",
            event_count,
            "".join(h for h, _ in cards),
            see_all_url=f"{get_settings().site_url.rstrip('/')}/competitions",
        )
        event_text = "Hackathons & competitions\n\n" + "\n\n".join(t for _, t in cards)
        cards_text = "\n\n".join(part for part in [cards_text, event_text] if part)
        if not first_card:
            company = events[0].company.name if events[0].company else "Unknown"
            first_card = f"{events[0].title} at {company}"
    html = email_layout(
        title="Your daily opportunity digest",
        kind_label="Daily digest",
        greeting=greeting(display_name),
        summary=summary,
        preheader=summary + (f" — {first_card}" if first_card else ""),
        body_html=body,
        unsubscribe_url=unsub_url,
        cta_label="See all on Aspirova",
        cta_url=get_settings().site_url,
    )
    text = "\n\n".join([greeting(display_name), summary, cards_text, text_footer(unsub_url)])
    return html, text


def _render_closing_soon(
    opportunities: list[models.Opportunity],
    now: datetime,
    unsub_url: str | None = None,
    *,
    display_name: str | None = None,
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

    items = sorted(
        (o for o in opportunities if o.deadline is not None), key=lambda o: _utc(o.deadline)
    )
    cards = [
        opportunity_card(o, now=now, button_url=o.apply_url, deadline_policy="any")[0]
        for o in items
    ]
    count = len(opportunities)
    summary = (
        f"{count} saved {'opportunity closes' if count == 1 else 'opportunities close'} "
        "in the next 3 days"
    )
    html = email_layout(
        title="Opportunities closing soon",
        kind_label="Closing soon",
        unsubscribe_url=unsub_url,
        greeting=greeting(display_name),
        summary=summary,
        preheader=summary,
        body_html="".join(cards)
        + (
            f'<p class="em-muted" style="color:{MUTED};font-size:14px;line-height:20px">'
            "Deadlines can change. Please verify them at the linked source.</p>"
        ),
        cta_label="Review your saved opportunities",
        cta_url=f"{get_settings().site_url.rstrip('/')}/saved",
    )
    return subject, html


def _render_closing_soon_text(
    opportunities: list[models.Opportunity],
    unsub_url: str | None = None,
    *,
    display_name: str | None = None,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(timezone.utc)
    items = sorted(
        (o for o in opportunities if o.deadline is not None), key=lambda o: _utc(o.deadline)
    )
    cards = [
        opportunity_card(o, now=current, button_url=o.apply_url, deadline_policy="any")[1]
        for o in items
    ]
    return "\n\n".join(
        [
            greeting(display_name),
            "Your bookmarked opportunities are closing soon:",
            *cards,
            "Deadlines can change. Please verify them at the linked source.",
            text_footer(unsub_url),
        ]
    )


class _HackathonPicks:
    """The day's hackathon picks, re-chosen only for a reader who already saw one.

    Every reader shares the default picks, selected once per run as before. A
    reader whose recent digests already carried one of them gets picks chosen
    with everything recently sent to them excluded, cached per exclusion set so
    readers with the same history share one selection.
    """

    def __init__(self, session: Session, now: datetime) -> None:
        self._session = session
        self._now = now
        self._excluding: dict[frozenset[int], list[models.Opportunity]] = {}

    @cached_property
    def default(self) -> list[models.Opportunity]:
        return _hackathon_digest_opportunities(self._session, self._now)

    def for_reader(self, recent_ids: frozenset[int]) -> list[models.Opportunity]:
        if not recent_ids.intersection(o.id for o in self.default):
            return self.default
        if recent_ids not in self._excluding:
            # Positional on purpose: tests replace the selector with *args stubs.
            self._excluding[recent_ids] = _hackathon_digest_opportunities(
                self._session, self._now, HACKATHON_DIGEST_SIZE, recent_ids
            )
        return self._excluding[recent_ids]


@dataclass
class DigestDraft:
    """One reader's digest as it would go out now. Empty means nothing to send."""

    window_start: datetime
    opportunities: list[models.Opportunity] = field(default_factory=list)
    hackathons: list[models.Opportunity] = field(default_factory=list)
    subject: str | None = None
    html: str | None = None
    text: str | None = None

    @property
    def empty(self) -> bool:
        return not self.opportunities and not self.hackathons


def compose_daily_digest(
    session: Session, user: models.User, now: datetime, picks: _HackathonPicks
) -> DigestDraft:
    """Select and render one reader's digest. Sends nothing and records nothing."""
    history = _digest_history(session, user.id, now)
    since = _digest_window_start(history, now)

    # Positional arguments on purpose: tests replace these selectors with
    # (session, user_id, *args) stubs.
    opportunities = [
        o
        for o in _dream_company_opportunities(session, user.id, since, now, history.recent_ids)
        if not _already_alerted(session, user.id, o.id)
    ]
    if not opportunities:
        # The generic fallback is a separate, unrelated query (all recent active
        # opportunities, not just dream-company ones) - it must ALSO exclude
        # already-alerted ones, or an opportunity excluded above (because a Pro
        # user's dream company already got it as an instant alert) can leak
        # right back in here, since it's still a perfectly real, recent, active
        # opportunity as far as this second query is concerned.
        opportunities = [
            o
            for o in _generic_recent_opportunities(
                session, since, DIGEST_GENERIC_SAMPLE_SIZE, now, history.recent_ids
            )
            if not _already_alerted(session, user.id, o.id)
        ]
    job_ids = {o.id for o in opportunities}
    hackathons = (
        [o for o in picks.for_reader(history.recent_ids) if o.id not in job_ids]
        if wants(user, "hackathon_digest")
        else []
    )
    draft = DigestDraft(window_start=since, opportunities=opportunities, hackathons=hackathons)
    if draft.empty:
        return draft

    has_jobs = any(o.category not in _HACKATHON_CATEGORIES for o in opportunities)
    has_hackathons = bool(hackathons) or any(
        o.category in _HACKATHON_CATEGORIES for o in opportunities
    )
    if has_jobs and has_hackathons:
        draft.subject = COMBINED_DIGEST_SUBJECT
    elif has_hackathons:
        draft.subject = HACKATHON_DIGEST_SUBJECT
    else:
        draft.subject = DAILY_DIGEST_SUBJECT
    draft.html, draft.text = _render_digest(
        opportunities,
        unsubscribe_url(user.id, "daily_digest"),
        display_name=user.display_name,
        now=now,
        hackathons=hackathons,
    )
    return draft


def preview_daily_digest(
    session: Session, user: models.User, *, now: datetime | None = None
) -> DigestDraft:
    """What this reader's next digest would contain if it went out now.

    Read-only: nothing is sent or recorded, so a preview never counts toward the
    daily cap or the repeat guard.
    """
    now = _utc(now or datetime.now(timezone.utc))
    return compose_daily_digest(session, user, now, _HackathonPicks(session, now))


def send_daily_digests(session: Session, *, now: datetime | None = None) -> dict:
    now = _utc(now or datetime.now(timezone.utc))

    result = {"sent": 0, "failed": 0, "skipped_capped": 0, "skipped_empty": 0}
    picks = _HackathonPicks(session, now)

    for user in session.scalars(select(models.User)).all():
        try:
            if not can(session, user, "daily_digest"):
                continue
            if not wants(user, "daily_digest"):
                continue
            if _already_sent_today(session, user.id, "digest", now):
                result["skipped_capped"] += 1
                continue

            draft = compose_daily_digest(session, user, now, picks)
            if draft.empty:
                result["skipped_empty"] += 1
                continue

            sent = send_email(
                user.email,
                draft.subject,
                draft.html,
                draft.text,
                headers=list_unsubscribe_headers(user.id, "daily_digest"),
            )
            _record_notification(
                session,
                user.id,
                "digest",
                opportunity_id=None,
                status="sent" if sent else "failed",
                meta={
                    "opportunity_ids": [o.id for o in draft.opportunities],
                    "hackathon_ids": [o.id for o in draft.hackathons],
                },
            )
            result["sent" if sent else "failed"] += 1
        except Exception:
            session.rollback()
            logger.exception("daily digest failed for user %s", user.id)
            result["failed"] += 1
            continue

    return result


def send_company_alerts(
    session: Session, *, now: datetime | None = None, instant_only: bool = False
) -> dict:
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    result = {
        "sent": 0,
        "failed": 0,
        "skipped_not_eligible": 0,
        "skipped_capped": 0,
        "skipped_already_alerted": 0,
        "skipped_empty": 0,
    }
    users = session.scalars(
        select(models.User).where(
            select(models.DreamCompany.id)
            .where(models.DreamCompany.user_id == models.User.id)
            .exists()
        )
    ).all()
    for user in users:
        user_id = user.id
        try:
            if not user.email or not wants(user, "instant_alerts"):
                result["skipped_not_eligible"] += 1
                continue
            instant = can(session, user, "instant_alerts")
            if instant_only and not instant:
                result["skipped_not_eligible"] += 1
                continue
            if not instant and _already_sent_today(session, user_id, "instant_alert", now):
                result["skipped_capped"] += 1
                continue
            follow_query = (
                select(models.DreamCompany.id)
                .where(models.DreamCompany.user_id == user_id)
                .order_by(models.DreamCompany.created_at.asc(), models.DreamCompany.id.asc())
            )
            limit = can(session, user, "dream_companies_limit")
            if limit is not None:
                follow_query = follow_query.limit(limit)
            rows = session.execute(
                select(models.DreamCompany, models.Opportunity, models.Company)
                .select_from(models.DreamCompany)
                .join(
                    models.Opportunity,
                    models.Opportunity.company_id == models.DreamCompany.company_id,
                )
                .join(models.Company, models.Company.id == models.DreamCompany.company_id)
                .where(
                    models.DreamCompany.id.in_(follow_query),
                    models.Opportunity.status == "active",
                    models.Opportunity.is_hidden.is_not(True),
                    exclude_stale_opportunities(now),
                    exclude_experienced_only_opportunities(),
                    exclude_school_only_opportunities(),
                    exclude_closed_competitions(),
                    or_(models.Opportunity.deadline.is_(None), models.Opportunity.deadline >= now),
                    models.Opportunity.first_seen_at >= now - COMPANY_ALERT_LOOKBACK,
                    models.Opportunity.first_seen_at <= now,
                    models.Opportunity.first_seen_at > models.DreamCompany.created_at,
                    followed_company_match(),
                )
                .order_by(
                    models.DreamCompany.created_at.asc(),
                    models.DreamCompany.id.asc(),
                    models.Opportunity.first_seen_at.desc(),
                    models.Opportunity.id.desc(),
                )
            ).all()
            groups: dict[int, CompanyAlertGroup] = {}
            opportunity_ids = []
            for follow, opportunity, company in rows:
                if _already_alerted(session, user_id, opportunity.id, "instant_alert"):
                    result["skipped_already_alerted"] += 1
                    continue
                if company.id not in groups:
                    groups[company.id] = CompanyAlertGroup(company, list(follow.roles), [])
                groups[company.id].opportunities.append(opportunity)
                opportunity_ids.append(opportunity.id)
            if not opportunity_ids:
                result["skipped_empty"] += 1
                continue
            subject, html, text = render_company_alert(
                display_name=user.display_name,
                user_skills=user.skills,
                groups=list(groups.values()),
                unsub_url=unsubscribe_url(user_id, "instant_alerts"),
                now=now,
            )
            try:
                sent = send_email(
                    user.email,
                    subject,
                    html,
                    text,
                    headers=list_unsubscribe_headers(user_id, "instant_alerts"),
                )
            except Exception:
                logger.exception("company alert delivery failed for user %s", user_id)
                sent = False
            # Commit the complete group together, including cards covered by the more link.
            session.add_all(
                [
                    models.Notification(
                        user_id=user_id,
                        type="instant_alert",
                        opportunity_id=opportunity_id,
                        status="sent" if sent else "failed",
                        sent_at=now if sent else None,
                    )
                    for opportunity_id in opportunity_ids
                ]
            )
            session.commit()
            result["sent" if sent else "failed"] += 1
        except Exception:
            session.rollback()
            logger.exception("company alert failed for user %s", user_id)
            result["failed"] += 1
    return result


def send_instant_alerts(session: Session, *, now: datetime | None = None) -> dict:
    return send_company_alerts(session, now=now, instant_only=True)


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
                        models.Bookmark.status == "saved",
                        models.Opportunity.status == "active",
                        # A listing confirmed closed keeps status 'active' through its
                        # grace period, so status alone would still remind about it.
                        models.Opportunity.closed_at.is_(None),
                        models.Opportunity.is_hidden.is_not(True),
                        exclude_stale_opportunities(now),
                        # Only a deadline the source states: an inferred or unknown
                        # date must not be emailed as "closes in N days".
                        models.Opportunity.deadline_confidence == "explicit",
                        # Same cut-off as everywhere else: deadline <= now has passed.
                        models.Opportunity.deadline > now,
                        models.Opportunity.deadline <= cutoff,
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

            unsub_url = unsubscribe_url(user.id, "closing_soon")
            subject, html = _render_closing_soon(
                opportunities, now, unsub_url, display_name=user.display_name
            )
            text = _render_closing_soon_text(
                opportunities, unsub_url, display_name=user.display_name, now=now
            )
            sent = send_email(
                user.email,
                subject,
                html,
                text,
                headers=list_unsubscribe_headers(user.id, "closing_soon"),
            )
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
# Hackathon picks for the single daily digest
#
# Selected once per run and appended after each user's opportunity sections.
# This preserves a dedicated competition selection pool even when jobs dominate
# the corpus. A legacy hackathon opt-out suppresses the appended picks, while
# the daily-digest preference and UTC calendar-day cap control the one email.
# Merged on 2026-11-08 to stay within Resend's 100-emails/day free limit.
#
# Only still-enterable listings qualify, with the minimum lead and freshness
# window below. Reputed organisers retain reserved slots, and the existing
# source caps, deadline-day diversity and date-seeded shuffle remain in use.
# ---------------------------------------------------------------------------

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
    exclude_ids: frozenset[int] = frozenset(),
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
        # Closed on absence keeps status "active" during the grace window.
        models.Opportunity.closed_at.is_(None),
        *_not_in(exclude_ids),
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
