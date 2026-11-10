"""GET /feed - the main browse surface. No AI/heavy work on this hot path
(Doc 02 sec 3 hard rule) - just indexed Postgres queries.

total_count is fetched via a count(*) OVER() window function in the SAME
query as the page of results, not a separate count query - each query is a
real network round-trip to the Supabase pooler (measured ~44ms baseline per
round-trip), so halving the round-trips roughly halves latency. This is
what brought p95 back under the Phase-1 budget; the naive two-query version
measured p50 248-272ms / p95 up to 1254ms against the same real data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, and_, case, cast, func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import (
    ROLE_QUERY_PATTERN,
    SOURCE_GROUPS,
    competition_filters,
    competition_prize_expression,
    effective_posted_at,
    exclude_closed_competitions,
    exclude_closed_now,
    exclude_experienced_only_opportunities,
    exclude_school_only_opportunities,
    exclude_stale_opportunities,
    experience_filters,
    kind_filters,
    listing_closed,
    location_scope_filters,
    opportunity_filters,
    role_signal_filters,
    student_rank_expression,
)
from api.opportunity_loading import opportunity_list_load_options
from api.landing import famous_company_filter, landing_rows
from api.schemas import FeedResponse, OpportunityListItem
from core import models

router = APIRouter()


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    category: str | None = Query(
        None, pattern="^(internship|job|hackathon|competition|scholarship)$"
    ),
    kind: str | None = Query(None, pattern="^(roles|competitions)$"),
    remote: bool | None = Query(None),
    company: list[str] | None = Query(None),
    location: list[str] | None = Query(None),
    scope: str | None = Query(None, pattern="^(abroad|domestic|both)$"),
    country: str | None = Query(None, min_length=2, max_length=2),
    remote_abroad: bool = Query(False),
    prefer_country: str | None = Query(None, pattern="^[A-Za-z]{2}$"),
    source: str | None = Query(None, pattern="^(direct|unstop|remoteok|devpost)$"),
    experience: str | None = Query(None, pattern="^(early|new_grad)$"),
    comp_type: list[str] | None = Query(None),
    registration: str | None = Query(None),
    deadline_within: int | None = Query(None),
    organiser_type: list[str] | None = Query(None),
    mode: list[str] | None = Query(None),
    prize_min: int | None = Query(None, ge=0),
    status: str | None = Query(None, pattern="^(open|closed)$"),
    paid: bool | None = Query(None),
    min_stipend: int | None = Query(None, ge=0),
    part_time: bool | None = Query(None),
    max_duration: int | None = Query(None, ge=1, le=24),
    job_offer: bool | None = Query(None),
    posted_within: int | None = Query(None),
    role: str | None = Query(None, pattern=ROLE_QUERY_PATTERN),
    top: int | None = Query(None, gt=0),
    sort: str = Query("student", pattern="^(recent|deadline|student|prize)$"),
    prefer_logos: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FeedResponse:
    base_filters = [
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_school_only_opportunities(),
        exclude_closed_competitions() if status == "closed" else exclude_closed_now(),
        *opportunity_filters(category, remote, company, location, top),
        *experience_filters(experience),
        *role_signal_filters(
            paid, min_stipend, part_time, max_duration, job_offer, posted_within, role
        ),
        *location_scope_filters(scope, country, remote_abroad),
        *competition_filters(
            comp_type,
            registration,
            deadline_within,
            organiser_type,
            mode,
            prize_min,
            status,
        ),
    ]
    base_filters.extend(kind_filters(kind))
    if source is not None:
        base_filters.append(models.Opportunity.primary_source.in_(SOURCE_GROUPS[source]))

    is_closed = case((listing_closed(), 1), else_=0)
    total_count = func.count().over().label("total_count")
    open_count = func.count().filter(is_closed == 0).over().label("open_count")
    source_rank = None
    posted_at = effective_posted_at()
    posted_day = cast(func.timezone("UTC", posted_at), Date)
    if sort not in {"deadline", "prize"}:
        partition_by = [func.coalesce(models.Opportunity.primary_source, "")]
        source_posted_at = models.Opportunity.last_seen_at
        if sort == "recent":
            partition_by.append(posted_day)
            source_posted_at = posted_at
        source_rank = (
            func.row_number()
            .over(
                partition_by=partition_by,
                order_by=[
                    source_posted_at.desc(),
                    models.Opportunity.id.desc(),
                ],
            )
            .label("source_rank")
        )
    selected_columns = [models.Opportunity, total_count, open_count]
    if source_rank is not None:
        selected_columns.append(source_rank)
    # id is a required tie-breaker, not cosmetic: many rows share the exact
    # same last_seen_at (same crawl batch) or deadline (often null), and
    # Postgres gives no ordering guarantee among tied rows across separate
    # paginated queries - confirmed live, page 1 and page 2 returned
    # overlapping rows without this.
    # The landing-page preference applies to the unfiltered first student page.
    has_filters = (
        remote_abroad
        or kind not in {None, "roles"}
        or any(
            value is not None
            for value in (
                category,
                remote,
                company,
                location,
                scope,
                country,
                source,
                experience,
                comp_type,
                registration,
                deadline_within,
                organiser_type,
                mode,
                prize_min,
                status,
                paid,
                min_stipend,
                part_time,
                max_duration,
                job_offer,
                posted_within,
                role,
                top,
            )
        )
    )
    landing = prefer_logos and page == 1 and sort == "student" and not has_filters
    if landing:
        has_logo = models.Opportunity.company.has(models.Company.logo_url.is_not(None))
        # Freeze original source order and logo-eligible totals before quota selection.
        source_ranks = (
            select(
                models.Opportunity.id,
                source_rank,
                func.count().filter(has_logo).over().label("total_count"),
                func.count().filter(and_(has_logo, is_closed == 0)).over().label("open_count"),
            )
            .where(*base_filters)
            .subquery()
        )
        base_filters.append(has_logo)
        source_rank = source_ranks.c.source_rank
        selected_columns[1:3] = [source_ranks.c.total_count, source_ranks.c.open_count]
        selected_columns[-1] = source_rank
    query = select(*selected_columns).options(*opportunity_list_load_options()).where(*base_filters)
    if landing:
        query = query.join_from(
            models.Opportunity, source_ranks, source_ranks.c.id == models.Opportunity.id
        )
    ordering = [is_closed.asc()]
    if kind == "roles" and sort != "prize":
        roles_first = case(
            (models.Opportunity.category.in_(["internship", "job"]), 0),
            else_=1,
        )
        ordering.append(roles_first.asc())

    if prefer_country is not None and sort in {"student", "recent"}:
        preferred_country = case(
            (models.Opportunity.country == prefer_country.upper(), 0),
            (
                and_(
                    models.Opportunity.is_remote.is_(True),
                    func.btrim(func.coalesce(models.Opportunity.country, "")) == "",
                ),
                1,
            ),
            else_=2,
        )
        ordering.append(preferred_country.asc())

    student_rank = student_rank_expression()

    if sort == "prize":
        ordering.extend(
            [
                competition_prize_expression().desc().nullslast(),
                models.Opportunity.deadline.asc().nullslast(),
                models.Opportunity.id.asc(),
            ]
        )
    elif sort == "deadline":
        open_deadline = case(
            (is_closed == 0, models.Opportunity.deadline),
            else_=None,
        )
        ordering.extend(
            [
                open_deadline.asc().nullslast(),
                models.Opportunity.deadline.desc().nullslast(),
                models.Opportunity.id.asc(),
            ]
        )
    elif sort == "student":
        ordering.extend(
            [
                student_rank.asc(),
                source_rank.asc(),
                models.Opportunity.last_seen_at.desc(),
                models.Opportunity.id.desc(),
            ]
        )
    else:
        ordering.extend(
            [
                posted_day.desc(),
                source_rank.asc(),
                posted_at.desc(),
                models.Opportunity.id.desc(),
            ]
        )
    query = query.order_by(*ordering)

    if landing:
        rows = landing_rows(
            db,
            query,
            models.Opportunity.company.has(famous_company_filter()),
            limit,
            listing_order=ordering,
        )
    else:
        rows = db.execute(query.offset((page - 1) * limit).limit(limit)).unique().all()

    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0
    open_total = rows[0].open_count if rows else 0

    return FeedResponse(items=items, total=total, open_total=open_total, page=page, limit=limit)
