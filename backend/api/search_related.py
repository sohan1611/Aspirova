"""Canonical programme/company matches alongside the existing listing search."""

from datetime import datetime
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from api.company import company_search_matches
from api.deps import get_db
from api.filters import SOURCE_GROUPS
from api.schemas import CompanyListItem
from api.search import search_base_filters, search_expressions, trimmed_search_query
from core import models
from core.calendar_public import CalendarEdition, current_calendar_item
from core.entity_search import (
    PROGRAMME_MATCH_ORDER,
    CompanyMatch,
    ProgrammeMatch,
    match_programme,
    normalize,
)
from core.hiring_calendar import IST
from core.programme_labels import PROGRAMME_CATEGORY_LABELS

router = APIRouter()

# Match the existing frontend source-filter labels.
SOURCE_LABELS = {
    "direct": "Direct from company",
    "unstop": "Unstop",
    "remoteok": "RemoteOK",
    "devpost": "Devpost",
    "other": "Other sources",
}


class RelatedProgramme(BaseModel):
    entity_type: Literal["programme"] = "programme"
    slug: str
    name: str
    organiser: str
    category: str
    category_label: str
    country: str | None
    match: ProgrammeMatch
    # Calendar precision fields preserve month-only tentative dates in the UI.
    edition: CalendarEdition | None
    deadline_rolling: bool
    path: str
    calendar_path: str
    official_url: str


class RelatedCompany(CompanyListItem):
    entity_type: Literal["company"] = "company"
    match: CompanyMatch
    path: str


class RelatedProgrammes(BaseModel):
    total: int
    items: list[RelatedProgramme]


class RelatedCompanies(BaseModel):
    total: int
    items: list[RelatedCompany]


class SourceCount(BaseModel):
    value: str
    label: str
    count: int


class RelatedListings(BaseModel):
    total: int
    by_source: list[SourceCount]


class SearchRelatedResponse(BaseModel):
    q: str
    programmes: RelatedProgrammes
    companies: RelatedCompanies
    listings: RelatedListings


def related_programmes(db: Session, q: str) -> RelatedProgrammes:
    # joinedload avoids selectinload's size-dependent batching (and N+1 reads).
    programmes = (
        db.execute(
            select(models.Programme)
            .options(joinedload(models.Programme.editions), joinedload(models.Programme.company))
            .where(models.Programme.is_active.is_(True))
        )
        .unique()
        .scalars()
        .all()
    )
    now = datetime.now(IST)
    matches = []
    for programme in programmes:
        kind = match_programme(
            q,
            slug=programme.slug,
            name=programme.name,
            organiser=programme.organiser,
            company=programme.company.name if programme.company else "",
        )
        if kind is None:
            continue
        item = current_calendar_item(programme, now)
        matches.append(
            RelatedProgramme(
                slug=programme.slug,
                name=programme.name,
                organiser=programme.organiser,
                category=programme.category,
                category_label=PROGRAMME_CATEGORY_LABELS.get(
                    programme.category, programme.category
                ),
                country=programme.country,
                match=kind,
                edition=item.edition if item else None,
                deadline_rolling=item.metadata.deadline_rolling if item else False,
                path=f"/programme/{programme.slug}",
                calendar_path=(
                    f"/calendar?item={quote(item.id, safe='')}"
                    if item
                    else f"/calendar?q={quote(programme.name, safe='')}"
                ),
                official_url=programme.url,
            )
        )
    matches.sort(
        key=lambda item: (
            PROGRAMME_MATCH_ORDER.index(item.match),
            {"open": 0, "announced": 0, "expected": 1, "closed": 2}.get(
                item.edition.status if item.edition else "", 3
            ),
            item.name.casefold(),
            item.slug,
        )
    )
    return RelatedProgrammes(total=len(matches), items=matches[:4])


def related_companies(db: Session, q: str) -> RelatedCompanies:
    matches = []
    domains: set[str] = set()
    names: set[str] = set()
    # Matches arrive best kind first, then most open roles, so the first row
    # for a domain or a normalized name is the one worth showing. Substring
    # matches are a fallback here: shown only when nothing stronger matched.
    candidates = company_search_matches(db, q, open_only=True)
    if any(kind != "substring" for _company, kind in candidates):
        candidates = [(company, kind) for company, kind in candidates if kind != "substring"]
    for company, kind in candidates:
        if not company.active_count and kind not in {"exact", "acronym"}:
            continue
        domain = company.domain.casefold().strip().rstrip(".") if company.domain else None
        name = normalize(company.name)
        if (domain and domain in domains) or name in names:
            continue
        if domain:
            domains.add(domain)
        names.add(name)
        matches.append(
            RelatedCompany(
                **company.model_dump(),
                match=kind,
                path=f"/companies/{quote(company.slug, safe='')}",
            )
        )
    return RelatedCompanies(total=len(matches), items=matches[:3])


@router.get("/search/related", response_model=SearchRelatedResponse)
def search_related(
    q: str = Query(..., min_length=1, max_length=200),
    db: Session = Depends(get_db),
) -> SearchRelatedResponse:
    q = trimmed_search_query(q)
    base_filters = search_base_filters()
    matches_fts, _rank, matches_trigram, _similarity = search_expressions(q)
    source_group = case(
        *(
            (models.Opportunity.primary_source.in_(sources), key)
            for key, sources in SOURCE_GROUPS.items()
        ),
        else_="other",
    )

    def grouped_counts(predicate) -> dict[str, int]:
        return dict(
            db.execute(
                select(source_group, func.count())
                .select_from(models.Opportunity)
                .where(*base_filters, predicate)
                .group_by(source_group)
            ).all()
        )

    counts = grouped_counts(matches_fts)
    if not counts:
        counts = grouped_counts(matches_trigram)
    include_entities = len(normalize(q)) >= 2
    return SearchRelatedResponse(
        q=q,
        programmes=(
            related_programmes(db, q) if include_entities else RelatedProgrammes(total=0, items=[])
        ),
        companies=(
            related_companies(db, q) if include_entities else RelatedCompanies(total=0, items=[])
        ),
        listings=RelatedListings(
            total=sum(counts.values()),
            by_source=[
                SourceCount(value=key, label=label, count=counts[key])
                for key, label in SOURCE_LABELS.items()
                if counts.get(key)
            ],
        ),
    )
