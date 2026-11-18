"""GET /search - tsvector full-text primary, pg_trgm fallback for typos /
queries that don't tokenize (Doc 02 sec 3.5). websearch_to_tsquery (not
to_tsquery) because it never raises on arbitrary user input.

Search totals are fetched with separate exact count-only queries. The old
count(*) OVER() saved a real ~44ms Supabase pooler round-trip when queries
were cheap, but production EXPLAIN for q=engineer (16,706 matches) showed the
tradeoff had flipped: the row query with the window took 504ms / 80,022 buffer
hits, the same row query without it took 173ms / 80,503, and a separate plain
count(*) took 27ms / 3,046. Keeping the count separate avoids making Postgres
materialise every match before returning the requested page, and it directly
distinguishes true zero-match queries from out-of-range pages.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
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
    listing_closed,
    location_scope_filters,
    opportunity_filters,
    pay_rank_expression,
    role_signal_filters,
    student_rank_expression,
)
from api.opportunity_loading import opportunity_list_load_options
from api.schemas import OpportunityListItem, SearchResponse
from core import models

router = APIRouter()

TRIGRAM_FALLBACK_THRESHOLD = 0.3


def _count_matches(db: Session, base_filters: list, search_predicate) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(models.Opportunity)
            .where(*base_filters)
            .where(search_predicate)
        )
        or 0
    )


def _search_ordering(sort: str, relevance, student_first: bool = False) -> list:
    if sort == "student" and student_first:
        return [
            case((listing_closed(), 1), else_=0).asc(),
            student_rank_expression().asc(),
            relevance.desc(),
            models.Opportunity.id.desc(),
        ]
    ordering = []
    if sort in {"recent", "deadline", "prize", "pay"}:
        is_closed = case((listing_closed(), 1), else_=0)
        ordering.append(is_closed.asc())
        if sort == "recent":
            if student_first:
                ordering.append(student_rank_expression().asc())
            ordering.append(effective_posted_at().desc())
        elif sort == "deadline":
            open_deadline = case((is_closed == 0, models.Opportunity.deadline), else_=None)
            if student_first:
                ordering.extend(
                    [
                        case((open_deadline.is_(None), 1), else_=0).asc(),
                        student_rank_expression().asc(),
                    ]
                )
            ordering.append(open_deadline.asc().nullslast())
        elif sort == "pay":
            pay_rank = pay_rank_expression()
            if student_first:
                ordering.extend(
                    [
                        case((pay_rank.is_(None), 1), else_=0).asc(),
                        student_rank_expression().asc(),
                    ]
                )
            ordering.append(pay_rank.desc().nullslast())
        else:
            ordering.append(competition_prize_expression().desc().nullslast())
    ordering.extend([relevance.desc(), models.Opportunity.id.desc()])
    return ordering


def search_base_filters(
    *,
    category: str | None = None,
    remote: bool | None = None,
    company: list[str] | None = None,
    location: list[str] | None = None,
    top: int | None = None,
    experience: str | None = None,
    paid: bool | None = None,
    min_stipend: int | None = None,
    part_time: bool | None = None,
    max_duration: int | None = None,
    job_offer: bool | None = None,
    posted_within: int | None = None,
    role: str | None = None,
    scope: str | None = None,
    country: str | None = None,
    remote_abroad: bool = False,
    comp_type: list[str] | None = None,
    registration: str | None = None,
    deadline_within: int | None = None,
    organiser_type: list[str] | None = None,
    mode: list[str] | None = None,
    prize_min: int | None = None,
    status: str | None = None,
    kind: str | None = None,
    source: str | None = None,
) -> list:
    extra_filters = opportunity_filters(category, remote, company, location, top)
    base_filters = [
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_school_only_opportunities(),
        exclude_closed_competitions() if status == "closed" else exclude_closed_now(),
        *extra_filters,
        *experience_filters(experience),
        *role_signal_filters(
            paid, min_stipend, part_time, max_duration, job_offer, posted_within, role
        ),
        *location_scope_filters(scope, country, remote_abroad),
        *competition_filters(
            comp_type, registration, deadline_within, organiser_type, mode, prize_min, status
        ),
    ]
    if kind == "competitions":
        base_filters.append(models.Opportunity.category.in_(["hackathon", "competition"]))
    elif kind == "roles":
        base_filters.append(
            or_(
                models.Opportunity.category.in_(["internship", "job"]),
                models.Opportunity.meta["offers_ppi"].as_boolean().is_(True),
                models.Opportunity.meta["offers_ppo"].as_boolean().is_(True),
            )
        )
    if source is not None:
        base_filters.append(models.Opportunity.primary_source.in_(SOURCE_GROUPS[source]))
    return base_filters


def search_expressions(q: str) -> tuple:
    """Shared FTS/trigram expressions; callers choose their counting strategy."""
    tsquery = func.websearch_to_tsquery("english", q)
    matches_fts = models.Opportunity.search_tsv.op("@@")(tsquery)
    similarity = func.similarity(models.Opportunity.title_normalized, q.lower())
    return (
        matches_fts,
        func.ts_rank(models.Opportunity.search_tsv, tsquery),
        similarity >= TRIGRAM_FALLBACK_THRESHOLD,
        similarity,
    )


def search_predicate(db: Session, q: str, base_filters: list) -> tuple:
    matches_fts, rank, matches_trigram, similarity = search_expressions(q)
    fts_total = _count_matches(db, base_filters, matches_fts)
    if fts_total:
        return matches_fts, rank, fts_total
    return matches_trigram, similarity, None


def trimmed_search_query(q: str) -> str:
    q = q.strip()
    if not 1 <= len(q) <= 200:
        raise HTTPException(422, "q must be 1 to 200 characters after trimming")
    return q


@router.get("/search", response_model=SearchResponse)
def search_opportunities(
    q: str = Query(..., min_length=1, max_length=200),
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
    sort: str = Query("student", pattern="^(recent|deadline|student|prize|pay)$"),
    students: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SearchResponse:
    student_first = students if students is not None else sort == "student"
    q = q.strip()
    if not q:
        return SearchResponse(items=[], total=0, query=q)
    base_filters = search_base_filters(
        category=category,
        remote=remote,
        company=company,
        location=location,
        top=top,
        experience=experience,
        paid=paid,
        min_stipend=min_stipend,
        part_time=part_time,
        max_duration=max_duration,
        job_offer=job_offer,
        posted_within=posted_within,
        role=role,
        scope=scope,
        country=country,
        remote_abroad=remote_abroad,
        comp_type=comp_type,
        registration=registration,
        deadline_within=deadline_within,
        organiser_type=organiser_type,
        mode=mode,
        prize_min=prize_min,
        status=status,
        kind=kind,
        source=source,
    )
    predicate, relevance, total = search_predicate(db, q, base_filters)
    if total is None:
        total = _count_matches(db, base_filters, predicate)
    offset = (page - 1) * limit
    if total == 0 or offset >= total:
        return SearchResponse(items=[], total=total, query=q)
    # id tie-breaker: rank/similarity ties are common (many non-matches tie
    # at rank 0, or share an identical trigram score) and Postgres gives no
    # ordering guarantee among tied rows across separate paginated queries
    # (same class of bug as api/feed.py's pagination - verified there).
    query = (
        select(models.Opportunity)
        .options(*opportunity_list_load_options())
        .where(*base_filters, predicate)
        .order_by(*_search_ordering(sort, relevance, student_first))
        .offset(offset)
        .limit(limit)
    )
    opportunities = db.execute(query).unique().scalars().all()
    items = [OpportunityListItem.from_model(opportunity) for opportunity in opportunities]
    return SearchResponse(items=items, total=total, query=q)
