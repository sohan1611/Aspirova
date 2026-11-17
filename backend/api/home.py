"""One private action desk, with at most four data queries and no per-item reads."""

from datetime import datetime, timedelta, timezone
from typing import Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api.auth import get_current_user
from api.bookmarks import list_bookmarks
from api.deps import get_db
from api.filters import followed_company_match, open_opportunity_filters
from api.opportunity_loading import opportunity_list_load_options
from api.schemas import OpportunityListItem, SavedOpportunityItem
from core import models
from core.alert_relevance import reader_skills
from core.calendar_public import build_calendar, default_calendar_window
from core.hiring_calendar import IST
from core.interest_ranking import rank_profile_query
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis
from core.taxonomy import build_feed_terms

router = APIRouter()
NEW_ROLE_DAYS = 14
UNFINISHED_STAGES = frozenset({"planned", "applied", "assessment", "interviewing"})
T = TypeVar("T")


class DeskBlock(BaseModel, Generic[T]):
    items: list[T]
    reason: str | None = None
    count: int


class DeskDeadline(BaseModel):
    kind: Literal["listing", "programme"]
    slug: str
    title: str
    deadline: datetime
    confidence: Literal["explicit"] = "explicit"


class HomeDesk(BaseModel):
    matches: DeskBlock[OpportunityListItem]
    deadlines: DeskBlock[DeskDeadline]
    followed: DeskBlock[OpportunityListItem]
    applications: DeskBlock[SavedOpportunityItem]
    warnings: DeskBlock[SavedOpportunityItem]


async def enforce_home_desk_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    result = await check_rate_limit(
        get_redis(),
        bucket="home_desk",
        identifier=str(user.id),
        max_requests=30,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


def _application_order(item: SavedOpportunityItem) -> tuple[datetime, str]:
    """Mirror actionCenter.nextUpItems: assessment/interview date, else deadline."""
    when = item.deadline
    if item.bookmark_status in {"assessment", "interviewing"} and item.status_date:
        when = datetime.combine(item.status_date, datetime.min.time(), timezone.utc)
    return when or datetime.max.replace(tzinfo=timezone.utc), item.slug


def _warning(item: SavedOpportunityItem) -> bool:
    return bool(
        item.status == "withdrawn"
        or item.safety
        or (item.meta or {}).get("safety")
        or item.status in {"closed", "expired"}
        or item.closed_at
    )


def build_home_desk(db: Session, user: models.User, *, now: datetime) -> HomeDesk:
    # Reuse the saved-listing serializer/load profile, including #206 safety and
    # honest apply destinations. Archived entries are no longer tracked targets.
    saved = [item for item in list_bookmarks(db, user) if item.bookmark_status != "archived"]
    applications = sorted(
        (item for item in saved if item.bookmark_status in UNFINISHED_STAGES),
        key=_application_order,
    )
    warnings = [item for item in saved if _warning(item)]
    deadlines = [
        DeskDeadline(kind="listing", slug=item.slug, title=item.title, deadline=item.deadline)
        for item in saved
        if item.deadline_confidence == "explicit"
        and item.deadline
        and item.deadline >= now
        and item.status == "active"
        and not item.is_hidden
        and not _warning(item)
    ]

    # joinedload rather than selectinload keeps this one query even for many
    # watches/editions. Calendar selection owns recurrence, precision and basis.
    programmes = list(
        db.scalars(
            select(models.Programme)
            .join(models.ProgrammeWatch)
            .options(joinedload(models.Programme.editions))
            .where(
                models.ProgrammeWatch.user_id == user.id,
                models.Programme.is_active.is_(True),
            )
        ).unique()
    )
    start, end = default_calendar_window(now.astimezone(IST).date())
    calendar = build_calendar(programmes, start, end, categories=[], statuses=[], q="", now=now)
    deadlines.extend(
        DeskDeadline(
            kind="programme",
            slug=item.programme.slug,
            title=item.programme.name,
            deadline=item.edition.closes_at,
        )
        for item in calendar.items
        if item.edition.basis == "official"
        and item.edition.status in {"open", "announced"}
        and item.edition.closes_precision == "day"
        and not item.metadata.deadline_rolling
        and item.edition.closes_at
        and item.edition.closes_at >= now
    )
    deadlines.sort(key=lambda item: (item.deadline, item.kind, item.slug))

    skills = reader_skills(user)
    terms = build_feed_terms(user.field_profile or {}, skills)
    matches = []
    if terms or skills:
        query = (
            select(models.Opportunity)
            .options(*opportunity_list_load_options())
            .where(
                *open_opportunity_filters(),
                models.Opportunity.meta["safety"].astext.is_(None),
                models.Opportunity.category.in_(["internship", "job"]),
                models.Opportunity.first_seen_at >= now - timedelta(days=NEW_ROLE_DAYS),
                models.Opportunity.first_seen_at <= now,
                ~select(models.Bookmark.opportunity_id)
                .where(
                    models.Bookmark.user_id == user.id,
                    models.Bookmark.opportunity_id == models.Opportunity.id,
                )
                .exists(),
            )
        )
        matches = [
            OpportunityListItem.from_model(item)
            for item in db.scalars(rank_profile_query(query, terms, skills).limit(5))
        ]

    followed = [
        OpportunityListItem.from_model(item)
        for item in db.scalars(
            select(models.Opportunity)
            .join(
                models.DreamCompany,
                models.DreamCompany.company_id == models.Opportunity.company_id,
            )
            .options(*opportunity_list_load_options())
            .where(
                models.DreamCompany.user_id == user.id,
                followed_company_match(),
                *open_opportunity_filters(),
                models.Opportunity.meta["safety"].astext.is_(None),
                models.Opportunity.category.in_(["internship", "job"]),
                models.Opportunity.first_seen_at >= now - timedelta(days=NEW_ROLE_DAYS),
                models.Opportunity.first_seen_at <= now,
            )
            .order_by(models.Opportunity.first_seen_at.desc(), models.Opportunity.id.desc())
            .limit(3)
        )
    ]
    return HomeDesk(
        matches=DeskBlock(
            items=matches,
            count=len(matches),
            reason=None if matches else "no_new_matches" if terms or skills else "no_profile",
        ),
        deadlines=DeskBlock(
            items=deadlines[:3], count=len(deadlines), reason=None if deadlines else "no_deadlines"
        ),
        followed=DeskBlock(
            items=followed,
            count=len(followed),
            reason=None if followed else "no_recent_followed_roles",
        ),
        applications=DeskBlock(
            items=applications[:3],
            count=len(applications),
            reason=None if applications else "no_applications",
        ),
        warnings=DeskBlock(
            items=warnings[:3], count=len(warnings), reason=None if warnings else "no_warnings"
        ),
    )


@router.get("/home/desk", response_model=HomeDesk)
def get_home_desk(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_home_desk_limit),
) -> HomeDesk:
    response.headers["Cache-Control"] = "no-store"
    return build_home_desk(db, user, now=datetime.now(timezone.utc))
