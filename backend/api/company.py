"""Company landing-page endpoint for SSR company opportunity pages."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, false, func, or_, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import (
    exclude_closed_now,
    exclude_experienced_only_opportunities,
    exclude_school_only_opportunities,
    exclude_stale_opportunities,
)
from api.opportunity_loading import opportunity_list_load_options
from api.landing import famous_company_filter, landing_rows
from api.schemas import (
    CompanyListItem,
    CompanyPage,
    CompanySummary,
    OpportunityListItem,
)
from core import models
from core.entity_search import COMPANY_MATCH_ORDER, CompanyMatch, match_company, normalize
from core.external_companies import EXTERNAL_COMPANIES
from pipeline.normalize import normalize_company_name

router = APIRouter()


@router.get("/companies/external", response_model=dict[str, CompanySummary])
def external_companies(db: Session = Depends(get_db)) -> dict[str, CompanySummary]:
    keys = {entry["slug"]: normalize_company_name(entry["name"]) for entry in EXTERNAL_COMPANIES}
    companies = db.scalars(
        select(models.Company).where(models.Company.name_normalized.in_(keys.values()))
    ).all()
    by_name = {company.name_normalized: company for company in companies}
    return {
        slug: CompanySummary.model_validate(by_name[key])
        for slug, key in keys.items()
        if key in by_name
    }


@router.get("/companies/search", response_model=list[CompanyListItem])
def search_companies(
    q: str = Query(...),
    limit: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
) -> list[CompanyListItem]:
    q = q.strip()
    if not 2 <= len(q) <= 80:
        raise HTTPException(status_code=422, detail="q must be 2 to 80 characters after trimming")
    return [item for item, _kind in company_search_matches(db, q)[:limit]]


def company_search_matches(
    db: Session, q: str, *, open_only: bool = False
) -> list[tuple[CompanyListItem, CompanyMatch]]:
    """Read company candidates, then count listings only for Python-matched ids.

    Substrings are a collection-wide fallback, used only without any stronger
    match. Read scalar columns only: no relationship loads per matched company.
    """
    query = normalize(q)
    name = func.lower(models.Company.name)
    normalized_name = func.regexp_replace(name, "[^[:alnum:]]+", " ", "g")
    candidate_filters = []
    if query:
        first = query[0]
        candidate_filters = [
            name.like(f"{first}%"),
            name.op("~")(f"^(the|of|and|for|in|at|on|to)[^[:alnum:]]+{first}"),
            normalized_name.op("~")(f"(^| ){query}( |$)"),
        ]
        if len(query) >= 4:
            candidate_filters.append(normalized_name.like(f"%{query}%"))
    # SQL lower() does not fold accents as the Python matcher does. That recall
    # limitation is accepted here (the old ILIKE did not fold accents either).
    rows = db.execute(
        select(
            models.Company.id,
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
        ).where(or_(*candidate_filters) if candidate_filters else false())
    ).all()
    # Substring rows (queries of 4+ characters) stay, ranked last, so the follow-company search keeps
    # "Microsoft Research" for "research". /search/related drops them when anything stronger matched.
    matches = [(row, kind) for row in rows if (kind := match_company(q, row.name)) is not None]
    listing_filters = [
        models.Opportunity.company_id.in_([row.id for row, _kind in matches]),
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_school_only_opportunities(),
    ]
    if open_only:
        listing_filters.append(exclude_closed_now())
    counts = dict(
        db.execute(
            select(models.Opportunity.company_id, func.count(models.Opportunity.id))
            .where(*listing_filters)
            .group_by(models.Opportunity.company_id)
        ).all()
    )
    results = [
        (
            CompanyListItem(
                slug=row.slug,
                name=row.name,
                domain=row.domain,
                logo_url=row.logo_url,
                active_count=counts.get(row.id, 0),
            ),
            kind,
        )
        for row, kind in matches
    ]
    results.sort(
        key=lambda match: (
            COMPANY_MATCH_ORDER.index(match[1]),
            -match[0].active_count,
            match[0].name.casefold(),
            match[0].slug,
        )
    )
    return results


@router.get("/companies/top", response_model=list[CompanyListItem])
def list_top_companies(
    limit: int = Query(12, ge=1, le=24),
    prefer_logos: bool = Query(False),
    db: Session = Depends(get_db),
) -> list[CompanyListItem]:
    query = (
        select(
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
            func.count(models.Opportunity.id).label("active_count"),
        )
        .join(
            models.Opportunity,
            (models.Opportunity.company_id == models.Company.id)
            & (models.Opportunity.status == "active")
            & exclude_stale_opportunities()
            & exclude_experienced_only_opportunities()
            & exclude_school_only_opportunities(),
        )
        .group_by(
            models.Company.id,
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
            models.Company.prestige_rank,
            models.Company.global_rank,
        )
    )
    if prefer_logos:
        query = query.where(models.Company.logo_url.is_not(None)).order_by(
            func.coalesce(models.Company.prestige_rank, models.Company.global_rank)
            .asc()
            .nullslast(),
            models.Company.name.asc(),
            models.Company.id.asc(),
        )
        rows = landing_rows(db, query, famous_company_filter(), limit)
    else:
        query = query.where(models.Company.prestige_rank.is_not(None)).order_by(
            models.Company.prestige_rank.asc(), models.Company.name.asc()
        )
        rows = db.execute(query.limit(limit)).all()

    return [
        CompanyListItem(
            slug=row.slug,
            name=row.name,
            domain=row.domain,
            logo_url=row.logo_url,
            active_count=row.active_count,
        )
        for row in rows
    ]


@router.get("/companies", response_model=list[CompanyListItem])
def list_companies(db: Session = Depends(get_db)) -> list[CompanyListItem]:
    rows = db.execute(
        select(
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
            func.count(models.Opportunity.id).label("active_count"),
        )
        .join(
            models.Opportunity,
            (models.Opportunity.company_id == models.Company.id)
            & (models.Opportunity.status == "active")
            & exclude_stale_opportunities()
            & exclude_experienced_only_opportunities()
            & exclude_school_only_opportunities(),
        )
        .group_by(
            models.Company.id,
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
        )
        .order_by(desc("active_count"), models.Company.name.asc())
    ).all()

    return [
        CompanyListItem(
            slug=slug,
            name=name,
            domain=domain,
            logo_url=logo_url,
            active_count=active_count,
        )
        for slug, name, domain, logo_url, active_count in rows
    ]


@router.get("/company/{slug}", response_model=CompanyPage)
def get_company_page(
    slug: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CompanyPage:
    company = db.scalar(select(models.Company).where(models.Company.slug == slug))
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    total_count = func.count().over().label("total_count")
    query = (
        select(models.Opportunity, total_count)
        .options(*opportunity_list_load_options())
        .where(
            models.Opportunity.company_id == company.id,
            models.Opportunity.status == "active",
            exclude_stale_opportunities(),
            exclude_experienced_only_opportunities(),
            exclude_school_only_opportunities(),
        )
        .order_by(models.Opportunity.first_seen_at.desc(), models.Opportunity.id.desc())
    )

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).unique().all()
    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0

    return CompanyPage(
        company=CompanySummary.model_validate(company),
        items=items,
        total=total,
        page=page,
        limit=limit,
    )
