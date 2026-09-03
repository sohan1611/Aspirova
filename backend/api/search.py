"""GET /search - tsvector full-text primary, pg_trgm fallback for typos /
queries that don't tokenize (Doc 02 sec 3.5). websearch_to_tsquery (not
to_tsquery) because it never raises on arbitrary user input.

Each branch fetches its count via count(*) OVER() in the same query as the
page of results (see api/feed.py for why - it's a real ~44ms network round-
trip per query against the Supabase pooler, not free). That count only
rides on a returned row though, so a page that overshoots the real result
set comes back just as empty as a true zero-match query would - the two
are distinguished with one extra cheap count-only query, run ONLY when the
requested page came back empty (the common case, where rows ARE returned,
stays at one round-trip).
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
    total_count = func.count().over().label("total_count")

    # id tie-breaker: rank/similarity ties are common (many non-matches tie
    # at rank 0, or share an identical trigram score) and Postgres gives no
    # ordering guarantee among tied rows across separate paginated queries
    # (same class of bug as api/feed.py's pagination - verified there).
    fts_query = (
        select(models.Opportunity, total_count)
        .options(*opportunity_list_load_options())
        .where(*base_filters)
        .where(matches_fts)
        .order_by(rank.desc(), models.Opportunity.id.desc())
    )
    rows = db.execute(fts_query.offset((page - 1) * limit).limit(limit)).unique().all()

    if rows:
        items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
        return SearchResponse(items=items, total=rows[0].total_count, query=q)

    # No rows on THIS page - could be a true zero-match query (try the
    # trigram fallback) or a real result set that this page overshot
    # (report the real total, no fallback). Telling these apart needs an
    # explicit count, since the window-function count had no row to ride.
    fts_total = (
        db.scalar(
            select(func.count())
            .select_from(models.Opportunity)
            .where(*base_filters)
            .where(matches_fts)
        )
        or 0
    )
    if fts_total > 0:
        return SearchResponse(items=[], total=fts_total, query=q)

    similarity = func.similarity(models.Opportunity.title_normalized, q.lower())
    fallback_query = (
        select(models.Opportunity, total_count)
        .options(*opportunity_list_load_options())
        .where(*base_filters)
        .where(similarity >= TRIGRAM_FALLBACK_THRESHOLD)
        .order_by(similarity.desc(), models.Opportunity.id.desc())
    )
    rows = db.execute(fallback_query.offset((page - 1) * limit).limit(limit)).unique().all()

    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0
    return SearchResponse(items=items, total=total, query=q)
