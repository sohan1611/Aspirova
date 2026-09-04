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

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import (
    SOURCE_GROUPS,
    exclude_closed_competitions,
    exclude_experienced_only_opportunities,
    exclude_school_only_opportunities,
    exclude_stale_opportunities,
    experience_filters,
    location_scope_filters,
    opportunity_filters,
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
    experience: str | None = Query(None, pattern="^(early)$"),
    top: int | None = Query(None, gt=0),
    # Search stays relevance-ranked, but accepts the feed control's sort values.
    sort: str = Query("student", pattern="^(recent|deadline|student)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SearchResponse:
    extra_filters = opportunity_filters(category, remote, company, location, top)
    base_filters = [
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_school_only_opportunities(),
        exclude_closed_competitions(),
        *extra_filters,
        *experience_filters(experience),
        *location_scope_filters(scope, country, remote_abroad),
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
    tsquery = func.websearch_to_tsquery("english", q)
    matches_fts = models.Opportunity.search_tsv.op("@@")(tsquery)
    rank = func.ts_rank(models.Opportunity.search_tsv, tsquery)
    offset = (page - 1) * limit

    # id tie-breaker: rank/similarity ties are common (many non-matches tie
    # at rank 0, or share an identical trigram score) and Postgres gives no
    # ordering guarantee among tied rows across separate paginated queries
    # (same class of bug as api/feed.py's pagination - verified there).
    fts_total = _count_matches(db, base_filters, matches_fts)
    if fts_total > 0:
        if offset >= fts_total:
            return SearchResponse(items=[], total=fts_total, query=q)

        fts_query = (
            select(models.Opportunity)
            .options(*opportunity_list_load_options())
            .where(*base_filters)
            .where(matches_fts)
            .order_by(rank.desc(), models.Opportunity.id.desc())
        )
        opportunities = db.execute(fts_query.offset(offset).limit(limit)).unique().scalars().all()
        items = [OpportunityListItem.from_model(opportunity) for opportunity in opportunities]
        return SearchResponse(items=items, total=fts_total, query=q)

    similarity = func.similarity(models.Opportunity.title_normalized, q.lower())
    matches_trigram = similarity >= TRIGRAM_FALLBACK_THRESHOLD
    fallback_total = _count_matches(db, base_filters, matches_trigram)
    if fallback_total == 0 or offset >= fallback_total:
        return SearchResponse(items=[], total=fallback_total, query=q)

    fallback_query = (
        select(models.Opportunity)
        .options(*opportunity_list_load_options())
        .where(*base_filters)
        .where(matches_trigram)
        .order_by(similarity.desc(), models.Opportunity.id.desc())
    )
    opportunities = db.execute(fallback_query.offset(offset).limit(limit)).unique().scalars().all()

    items = [OpportunityListItem.from_model(opportunity) for opportunity in opportunities]
    return SearchResponse(items=items, total=fallback_total, query=q)
