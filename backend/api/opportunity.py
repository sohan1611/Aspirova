"""GET /opportunity/{slug} - the SSR-able detail endpoint (Doc 01 sec 11
HANDOFF: every opportunity needs a clean, indexable detail view)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_db
from api.filters import (
    exclude_closed_competitions,
    exclude_experienced_only_opportunities,
    exclude_school_only_opportunities,
    exclude_stale_opportunities,
    is_stale_opportunity,
)
from api.opportunity_loading import opportunity_list_load_options
from api.schemas import OpportunityDetail, OpportunityListItem, ReopenEstimateSchema
from core import models
from pipeline.reopen import reopen_estimate

router = APIRouter()


@router.get("/opportunity/{slug}/similar", response_model=list[OpportunityListItem])
def get_similar_opportunities(
    slug: str,
    limit: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
) -> list[OpportunityListItem]:
    target = db.scalar(
        select(models.Opportunity)
        .options(joinedload(models.Opportunity.company))
        .where(models.Opportunity.slug == slug)
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    match_conditions = []
    relevance_tiers = []
    if target.company_id is not None:
        same_company = models.Opportunity.company_id == target.company_id
        match_conditions.append(same_company)
        relevance_tiers.append((same_company, 0))
    if target.category is not None and target.country is not None:
        relevance_tiers.append(
            (
                (models.Opportunity.category == target.category)
                & (models.Opportunity.country == target.country),
                1,
            )
        )
    if target.category is not None:
        same_category = models.Opportunity.category == target.category
        match_conditions.append(same_category)
        relevance_tiers.append((same_category, 2))
    if target.country is not None:
        same_country = models.Opportunity.country == target.country
        match_conditions.append(same_country)
        relevance_tiers.append((same_country, 3))

    filters = [
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_school_only_opportunities(),
        exclude_closed_competitions(),
        models.Opportunity.id != target.id,
    ]
    if match_conditions:
        filters.append(or_(*match_conditions))

    relevance = case(*relevance_tiers, else_=4) if relevance_tiers else literal(4)
    prestige = func.coalesce(
        models.Company.prestige_rank,
        models.Company.global_rank,
        2_147_483_647,
    )
    candidates = db.scalars(
        select(models.Opportunity)
        .outerjoin(models.Company)
        .options(*opportunity_list_load_options())
        .where(*filters)
        .order_by(
            relevance.asc(),
            models.Opportunity.first_seen_at.desc(),
            prestige.asc(),
            models.Opportunity.id.desc(),
        )
        .limit(limit)
    ).unique()

    return [OpportunityListItem.from_model(opportunity) for opportunity in candidates]


@router.get("/opportunity/{slug}", response_model=OpportunityDetail)
def get_opportunity(slug: str, db: Session = Depends(get_db)) -> OpportunityDetail:
    opportunity = db.scalar(
        select(models.Opportunity)
        .options(joinedload(models.Opportunity.company))
        .where(models.Opportunity.slug == slug)
    )
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    estimate = reopen_estimate(db, opportunity)
    estimate_schema = None
    if estimate is not None:
        estimate_schema = ReopenEstimateSchema(
            window=estimate.window,
            basis=estimate.basis,
            note=estimate.note,
        )
    return OpportunityDetail.from_model(
        opportunity,
        reopen_estimate=estimate_schema,
        is_stale=is_stale_opportunity(opportunity),
    )
