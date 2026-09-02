"""Facet lists for picker-style feed filters."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, select, text, true
from sqlalchemy.orm import Session, aliased

from api.deps import get_db
from api.filters import (
    COMP_TYPE_LABELS,
    COMPETITION_MODE_LABELS,
    DEADLINE_WITHIN_DAYS,
    REGISTRATION_LABELS,
    competition_mode_expression,
    exclude_closed_competitions,
    exclude_experienced_only_opportunities,
    exclude_stale_opportunities,
    kind_filters,
)
from api.programmes import (
    PROGRAMME_CATEGORY_LABELS,
    PROGRAMME_STATUS_LABELS,
    VALID_PROGRAMME_CATEGORIES,
)
from api.schemas import FacetOption, FacetsResponse
from core import models
from core.organisers import (
    ORGANISER_TYPE_LABELS,
    classify_organiser,
    organiser_type_expression,
)

router = APIRouter()


VALID_OPPORTUNITY_CATEGORIES = frozenset({"internship", "job", "hackathon", "competition"})


def _selected_category_values(
    category: list[str] | None,
    *,
    valid_values: frozenset[str],
    detail: str,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw_value in category or []:
        for part in raw_value.split(","):
            normalized = part.strip().lower()
            if not normalized:
                continue
            if normalized not in valid_values:
                raise HTTPException(status_code=422, detail=detail)
            if normalized in seen:
                continue
            selected.append(normalized)
            seen.add(normalized)
    return selected


@router.get("/facets", response_model=FacetsResponse)
def get_facets(
    kind: str | None = Query(None, pattern="^(roles|competitions)$"),
    category: list[str] | None = Query(None),
    source: str | None = Query(None, pattern="^(opportunities|programmes)$"),
    db: Session = Depends(get_db),
) -> FacetsResponse:
    if source == "programmes":
        programme_categories = _selected_category_values(
            category,
            valid_values=VALID_PROGRAMME_CATEGORIES,
            detail="Invalid category",
        )
        return _programme_facets(db, programme_categories)

    opportunity_categories = _selected_category_values(
        category,
        valid_values=VALID_OPPORTUNITY_CATEGORIES,
        detail="Invalid category",
    )
    base_filters = [
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_closed_competitions(),
    ]
    if opportunity_categories:
        base_filters.append(models.Opportunity.category.in_(opportunity_categories))
    base_filters.extend(kind_filters(kind))

    count_label = func.count(models.Opportunity.id).label("count")
    company_rows = db.execute(
        select(models.Company.slug, models.Company.name, count_label)
        .join(
            models.Opportunity,
            models.Opportunity.company_id == models.Company.id,
        )
        .where(*base_filters)
        .group_by(models.Company.slug, models.Company.name)
        .order_by(func.lower(models.Company.name).asc(), models.Company.name.asc())
    ).all()

    location_rows = db.execute(
        select(models.Opportunity.location, count_label)
        .where(
            *base_filters,
            models.Opportunity.location.is_not(None),
            models.Opportunity.location != "",
        )
        .group_by(models.Opportunity.location)
        .order_by(
            func.lower(models.Opportunity.location).asc(),
            models.Opportunity.location.asc(),
        )
    ).all()

    company_counts = [
        FacetOption(value=slug, label=name, count=count)
        for slug, name, count in company_rows
        if count > 0
    ]
    location_counts = [
        FacetOption(value=location, label=location, count=count)
        for location, count in location_rows
        if location is not None and count > 0
    ]

    competition_scope = kind == "competitions" or bool(
        set(opportunity_categories) & {"hackathon", "competition"}
    )
    comp_types: list[FacetOption] = []
    registrations: list[FacetOption] = []
    deadline_within: list[FacetOption] = []
    organiser_types: list[FacetOption] = []
    modes: list[FacetOption] = []
    if competition_scope:
        comp_types = _comp_type_facets(db, base_filters)
        registrations = _registration_facets(db, base_filters)
        deadline_within = _deadline_within_facets(db, base_filters)
        organiser_types = _organiser_type_facets(db, base_filters)
        modes = _mode_facets(db, base_filters)

    return FacetsResponse(
        # Deduplicated, order preserved. The counted facet groups by slug so each
        # option has a stable value, but two distinct companies can share a
        # display name - grouping by slug therefore emits that name twice, and
        # this legacy list has always been a distinct set of names.
        companies=list(dict.fromkeys(name for _slug, name, _count in company_rows)),
        locations=[location for location, _count in location_rows if location is not None],
        company_counts=company_counts,
        location_counts=location_counts,
        comp_types=comp_types,
        registrations=registrations,
        deadline_within=deadline_within,
        organiser_types=organiser_types,
        modes=modes,
    )


def _programme_base_filters(categories: list[str]) -> list:
    filters = [models.Programme.is_active.is_(True)]
    if categories:
        filters.append(models.Programme.category.in_(categories))
    return filters


def _programme_facets(db: Session, categories: list[str]) -> FacetsResponse:
    base_filters = _programme_base_filters(categories)
    return FacetsResponse(
        companies=[],
        locations=[],
        programme_categories=_programme_category_facets(db, base_filters),
        programme_fields=_programme_field_facets(db, base_filters),
        programme_organisers=_programme_organiser_facets(db, base_filters),
        programme_institution_types=_programme_institution_type_facets(db, base_filters),
        programme_statuses=_programme_status_facets(db, base_filters),
    )


def _programme_category_facets(db: Session, base_filters: list) -> list[FacetOption]:
    rows = db.execute(
        select(models.Programme.category, func.count(models.Programme.id).label("count"))
        .where(*base_filters)
        .group_by(models.Programme.category)
    ).all()
    counts = {value: count for value, count in rows if value in PROGRAMME_CATEGORY_LABELS}
    return [
        FacetOption(value=value, label=label, count=counts[value])
        for value, label in PROGRAMME_CATEGORY_LABELS.items()
        if value in counts and counts[value] > 0
    ]


def _programme_field_facets(db: Session, base_filters: list) -> list[FacetOption]:
    tag_element = (
        func.jsonb_array_elements_text(models.Programme.tags)
        .table_valued("tag")
        .render_derived(name="tag")
    )
    rows = db.execute(
        select(
            tag_element.c.tag,
            func.count(func.distinct(models.Programme.id)).label("count"),
        )
        .select_from(models.Programme)
        .join(tag_element, true())
        .where(*base_filters)
        .group_by(tag_element.c.tag)
        .order_by(
            func.count(func.distinct(models.Programme.id)).desc(),
            tag_element.c.tag.asc(),
        )
    ).all()
    return [
        FacetOption(value=tag, label=_humanize_programme_value(tag), count=count)
        for tag, count in rows
        if tag and count > 0
    ]


def _programme_organiser_facets(db: Session, base_filters: list) -> list[FacetOption]:
    rows = db.execute(
        select(models.Programme.organiser, func.count(models.Programme.id).label("count"))
        .where(*base_filters)
        .group_by(models.Programme.organiser)
        .order_by(
            func.lower(models.Programme.organiser).asc(),
            models.Programme.organiser.asc(),
        )
    ).all()
    return [
        FacetOption(value=organiser, label=organiser, count=count)
        for organiser, count in rows
        if organiser and count > 0
    ]


def _programme_institution_type_facets(
    db: Session,
    base_filters: list,
) -> list[FacetOption]:
    rows = db.execute(
        select(models.Programme.organiser, func.count(models.Programme.id).label("count"))
        .where(*base_filters)
        .group_by(models.Programme.organiser)
    ).all()
    counts: dict[str, int] = {}
    for organiser, count in rows:
        organiser_type = classify_organiser(organiser)
        counts[organiser_type] = counts.get(organiser_type, 0) + count
    return [
        FacetOption(value=value, label=label, count=counts[value])
        for value, label in ORGANISER_TYPE_LABELS.items()
        if counts.get(value, 0) > 0
    ]


def _programme_status_facets(db: Session, base_filters: list) -> list[FacetOption]:
    current_edition = aliased(models.ProgrammeEdition)
    edition_for_max_year = aliased(models.ProgrammeEdition)
    current_edition_year = (
        select(func.max(edition_for_max_year.year))
        .where(
            and_(
                edition_for_max_year.programme_id == models.Programme.id,
                edition_for_max_year.status != "discontinued",
            )
        )
        .correlate(models.Programme)
        .scalar_subquery()
    )
    rows = db.execute(
        select(current_edition.status, func.count(models.Programme.id).label("count"))
        .select_from(models.Programme)
        .outerjoin(
            current_edition,
            and_(
                current_edition.programme_id == models.Programme.id,
                current_edition.year == current_edition_year,
            ),
        )
        .where(*base_filters, current_edition.status.in_(tuple(PROGRAMME_STATUS_LABELS)))
        .group_by(current_edition.status)
    ).all()
    counts = {value: count for value, count in rows if value in PROGRAMME_STATUS_LABELS}
    return [
        FacetOption(value=value, label=label, count=counts[value])
        for value, label in PROGRAMME_STATUS_LABELS.items()
        if value in counts and counts[value] > 0
    ]


# Tags that .title() gets wrong. The registry vocabulary is small and curated,
# so this is a complete list rather than a heuristic - "cs" rendered as "Cs" and
# "ai" as "Ai" in the field filter.
_PROGRAMME_ACRONYM_LABELS = {"cs": "CS", "ai": "AI"}


def _humanize_programme_value(value: str) -> str:
    words = value.replace("-", " ").replace("_", " ").split()
    return " ".join(_PROGRAMME_ACRONYM_LABELS.get(word.lower(), word.title()) for word in words)


def _ordered_options(rows, labels: dict[str, str]) -> list[FacetOption]:
    counts = {value: count for value, count in rows if value in labels and count > 0}
    return [
        FacetOption(value=value, label=label, count=counts[value])
        for value, label in labels.items()
        if value in counts
    ]


def _comp_type_facets(db: Session, base_filters: list) -> list[FacetOption]:
    subtype = models.Opportunity.meta["subtype"].as_string()
    rows = db.execute(
        select(subtype.label("value"), func.count(models.Opportunity.id).label("count"))
        .where(*base_filters, subtype.in_(tuple(COMP_TYPE_LABELS)))
        .group_by(subtype)
    ).all()
    return _ordered_options(rows, COMP_TYPE_LABELS)


def _registration_facets(db: Session, base_filters: list) -> list[FacetOption]:
    is_paid = models.Opportunity.meta["is_paid"].as_boolean()
    rows = db.execute(
        select(is_paid.label("value"), func.count(models.Opportunity.id).label("count"))
        .where(*base_filters, is_paid.is_not(None))
        .group_by(is_paid)
    ).all()
    counts = {("paid" if value else "free"): count for value, count in rows if count > 0}
    return [
        FacetOption(value=value, label=label, count=counts[value])
        for value, label in REGISTRATION_LABELS.items()
        if value in counts
    ]


def _deadline_within_facets(db: Session, base_filters: list) -> list[FacetOption]:
    bucket = case(
        *[
            (
                models.Opportunity.deadline <= func.now() + text(f"interval '{days} days'"),
                str(days),
            )
            for days in DEADLINE_WITHIN_DAYS
        ],
        else_=None,
    )
    rows = db.execute(
        select(bucket.label("value"), func.count(models.Opportunity.id).label("count"))
        .where(
            *base_filters,
            models.Opportunity.deadline.is_not(None),
            models.Opportunity.deadline >= func.now(),
            models.Opportunity.deadline
            <= func.now() + text(f"interval '{DEADLINE_WITHIN_DAYS[-1]} days'"),
        )
        .group_by(bucket)
    ).all()
    bucket_counts = {int(value): count for value, count in rows if value is not None}
    return [
        FacetOption(
            value=str(days),
            label=f"Next {days} day{'s' if days != 1 else ''}",
            count=sum(count for bucket_days, count in bucket_counts.items() if bucket_days <= days),
        )
        for days in DEADLINE_WITHIN_DAYS
        if any(bucket_days <= days for bucket_days in bucket_counts)
    ]


def _organiser_type_facets(db: Session, base_filters: list) -> list[FacetOption]:
    organiser_type = organiser_type_expression(models.Company.name)
    rows = db.execute(
        select(organiser_type.label("value"), func.count(models.Opportunity.id).label("count"))
        .select_from(models.Opportunity)
        .outerjoin(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(*base_filters)
        .group_by(organiser_type)
    ).all()
    return _ordered_options(rows, ORGANISER_TYPE_LABELS)


def _mode_facets(db: Session, base_filters: list) -> list[FacetOption]:
    mode = competition_mode_expression()
    rows = db.execute(
        select(mode.label("value"), func.count(models.Opportunity.id).label("count"))
        .where(*base_filters, mode != "unknown")
        .group_by(mode)
    ).all()
    return _ordered_options(rows, COMPETITION_MODE_LABELS)
