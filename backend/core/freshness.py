"""Deterministic source cadence and verification; no reader-side writes or I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import DateTime, and_, case, cast, func, literal, or_, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement

from core import models
from core.destination_facts import is_positive_verification


@dataclass(frozen=True)
class Cadence:
    tier: int
    priority: int
    crawl_hours: int
    check_hours: int
    stale_hours: int
    target_hours: int


DEFAULT_CADENCE = Cadence(2, 20, 24, 72, 240, 96)
# Founder ruling: "10 months" means 305 days for stale-listing promotion.
STALE_AFTER_DAYS = 305
RESCUE_WINDOW_DAYS = 7
RESCUE_RECHECK_HOURS = 24
RESCUE_LIMIT = 100
RESCUE_MAX_SECONDS = 180
RESCUE_DELAY_SECONDS = 1
SOURCE_CADENCE = {
    **{
        key: Cadence(1, 10, 24, 24, 168, 48)
        for key in (
            "greenhouse",
            "lever",
            "ashby",
            "smartrecruiters",
            "recruitee",
            "workable",
            "keka",
            "amazon",
            "workday",
            "unstop",
            "github_lists",
        )
    },
    **{key: DEFAULT_CADENCE for key in ("devpost", "devfolio", "hackerearth")},
    **{
        key: Cadence(3, 30, 24, 168, 720, 240)
        for key in (
            "remoteok",
            "arbeitnow",
            "jobicy",
        )
    },
    "himalayas": Cadence(3, 30, 24, 168, 1440, 240),
    **{
        key: Cadence(2, 20, 24, 72, 1080, 96)
        for key in (
            "meity_careers",
            "nic_dii",
            "drdo",
            "nec_internships",
            "isro",
        )
    },
}


def cadence(source: str | None) -> Cadence:
    return SOURCE_CADENCE.get(source or "", DEFAULT_CADENCE)


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def last_verified(opportunity: models.Opportunity) -> datetime | None:
    facts = opportunity.destination_facts or {}
    positive = facts.get("last_alive_at")
    if is_positive_verification(facts):
        positive = max(
            filter(None, (_timestamp(positive), _timestamp(facts.get("checked_at")))), default=None
        )
    return max(
        filter(None, (_timestamp(opportunity.last_seen_at), _timestamp(positive))), default=None
    )


def is_age_stale(opportunity: models.Opportunity, now: datetime | None = None) -> bool:
    """Binding 2026-08-17: evergreen requisitions do not become new on re-seen."""
    current = now or datetime.now(timezone.utc)
    posted = _timestamp(opportunity.posted_at or opportunity.first_seen_at)
    deadline = _timestamp(opportunity.deadline)
    return bool(
        posted is not None
        and posted < current - timedelta(days=STALE_AFTER_DAYS)
        and (deadline is None or deadline <= current)
    )


def freshness_reason(
    opportunity: models.Opportunity, now: datetime | None = None
) -> Literal["age", "verification"] | None:
    if is_age_stale(opportunity, now):
        return "age"
    verified = last_verified(opportunity)
    if verified is None or verified < (now or datetime.now(timezone.utc)) - timedelta(
        hours=cadence(opportunity.primary_source).stale_hours
    ):
        return "verification"
    return None


def is_stale(opportunity: models.Opportunity, now: datetime | None = None) -> bool:
    return freshness_reason(opportunity, now) is not None


def cadence_value(
    field: Literal["tier", "priority", "crawl_hours", "check_hours", "stale_hours", "target_hours"],
) -> ColumnElement[int]:
    return case(
        {key: getattr(value, field) for key, value in SOURCE_CADENCE.items()},
        value=models.Opportunity.primary_source,
        else_=getattr(DEFAULT_CADENCE, field),
    )


def verified_expression() -> ColumnElement[datetime | None]:
    facts = models.Opportunity.destination_facts
    observation = facts["observation"]
    positive = case(
        (
            (facts["status"].astext == "alive")
            & or_(
                observation["http_status"].as_integer().between(200, 299),
                observation["http_status"].astext.is_(None)
                & (observation["same_posting"] == literal(True, type_=JSONB)),
            ),
            cast(facts["checked_at"].astext, DateTime(timezone=True)),
        ),
        else_=None,
    )
    return func.greatest(
        models.Opportunity.last_seen_at,
        cast(facts["last_alive_at"].astext, DateTime(timezone=True)),
        positive,
    )


def age_stale_expression(now: datetime | None = None) -> ColumnElement[bool]:
    current = literal(now) if now else func.now()
    cutoff = (
        now - timedelta(days=STALE_AFTER_DAYS)
        if now
        else current - text(f"interval '{STALE_AFTER_DAYS} days'")
    )
    return and_(
        func.coalesce(models.Opportunity.posted_at, models.Opportunity.first_seen_at) < cutoff,
        or_(models.Opportunity.deadline.is_(None), models.Opportunity.deadline <= current),
    ).is_(True)


def verification_stale_expression(now: datetime | None = None) -> ColumnElement[bool]:
    current = literal(now) if now else func.now()
    cutoff = current - func.make_interval(0, 0, 0, 0, cadence_value("stale_hours"))
    # Most rows have a recent crawl confirmation. Only parse destination evidence
    # when that confirmation cannot already prove freshness.
    return case(
        (models.Opportunity.last_seen_at >= cutoff, False),
        else_=func.coalesce(verified_expression() < cutoff, True),
    )


def stale_expression(now: datetime | None = None) -> ColumnElement[bool]:
    """One per-row predicate; deliberately no correlated queries on landing."""
    return or_(age_stale_expression(now), verification_stale_expression(now))
