"""Read API for the curated recurring programmes registry."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text, and_, any_, bindparam, cast, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, aliased, selectinload

from api.deps import get_db
from api.schemas import ProgrammeDetail, ProgrammeListItem, ProgrammeListResponse
from core import models
from core.organisers import ORGANISER_TYPE_LABELS, classify_organiser

router = APIRouter()
MAX_SELECTED_DIVISIONS = 30
PROGRAMME_TAG_MAP_PATH = Path(__file__).resolve().parents[1] / "data" / "programme_tag_map.json"
PROGRAMME_TAG_MAP: dict[str, list[str]] = json.loads(
    PROGRAMME_TAG_MAP_PATH.read_text(encoding="utf-8")
)["divisions"]

PROGRAMME_CATEGORY_LABELS = {
    "research_internship": "Research internship",
    "fellowship": "Fellowship",
    "government_internship": "Government internship",
    "open_source": "Open source",
    "international_research": "International research",
    "corporate_research": "Corporate research",
    "recurring_competition": "Recurring competition",
    "scholarship": "Scholarship",
    "conference": "Conference",
}
PROGRAMME_STATUS_LABELS = {
    "expected": "Expected",
    "announced": "Announced",
    "open": "Open",
    "closed": "Closed",
}
VALID_PROGRAMME_CATEGORIES = frozenset(PROGRAMME_CATEGORY_LABELS)
VALID_PROGRAMME_STATUSES = frozenset(PROGRAMME_STATUS_LABELS)


def _selected_values(
    values: list[str] | None,
    *,
    valid_values: frozenset[str] | None = None,
    detail: str = "Invalid filter",
    split_commas: bool = True,
    casefold: bool = True,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        parts = raw_value.split(",") if split_commas else [raw_value]
        for part in parts:
            normalized = part.strip()
            if casefold:
                normalized = normalized.lower()
            if not normalized:
                continue
            if valid_values is not None and normalized not in valid_values:
                raise HTTPException(status_code=422, detail=detail)
            if normalized in seen:
                continue
            selected.append(normalized)
            seen.add(normalized)
    return selected


def _selected_categories(category: list[str] | None) -> list[str]:
    return _selected_values(
        category,
        valid_values=VALID_PROGRAMME_CATEGORIES,
        detail="Invalid category",
    )


def _selected_statuses(status: list[str] | None) -> list[str]:
    return _selected_values(
        status,
        valid_values=VALID_PROGRAMME_STATUSES,
        detail="Invalid status",
    )


def _selected_fields(field: list[str] | None) -> list[str]:
    return _selected_values(field)


def _selected_organisers(organiser: list[str] | None) -> list[str]:
    return _selected_values(organiser, split_commas=False, casefold=False)


def _selected_institution_types(institution_type: list[str] | None) -> list[str]:
    return _selected_values(
        institution_type,
        valid_values=frozenset(ORGANISER_TYPE_LABELS),
        detail="Invalid institution_type",
    )


def _organisers_for_institution_types(
    db: Session,
    institution_types: list[str],
) -> list[str]:
    rows = db.execute(
        select(models.Programme.organiser)
        .where(models.Programme.is_active.is_(True))
        .group_by(models.Programme.organiser)
    ).all()
    return [
        organiser for (organiser,) in rows if classify_organiser(organiser) in institution_types
    ]


def _ilike_substring(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _selected_divisions(divisions: str | None) -> list[str]:
    """Parse known CSV division keys as a best-effort personalisation hint."""
    selected: list[str] = []
    seen: set[str] = set()
    for division in (divisions or "").split(","):
        normalized = division.strip().lower()
        if not normalized or normalized in seen or normalized not in PROGRAMME_TAG_MAP:
            continue
        selected.append(normalized)
        seen.add(normalized)
        if len(selected) == MAX_SELECTED_DIVISIONS:
            break
    return selected


def _tags_for_divisions(selected_divisions: list[str]) -> list[str]:
    selected_tags: list[str] = []
    seen: set[str] = set()
    for division in selected_divisions:
        for tag in PROGRAMME_TAG_MAP[division]:
            if tag in seen:
                continue
            selected_tags.append(tag)
            seen.add(tag)
    return selected_tags


@router.get("/programmes", response_model=ProgrammeListResponse)
def list_programmes(
    category: list[str] | None = Query(None),
    country: str | None = Query(None, min_length=2, max_length=2),
    status: list[str] | None = Query(None),
    field: list[str] | None = Query(None),
    organiser: list[str] | None = Query(None),
    institution_type: list[str] | None = Query(None),
    q: str | None = Query(None, max_length=200),
    divisions: str | None = Query(None, max_length=500),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ProgrammeListResponse:
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

    filters = [models.Programme.is_active.is_(True)]
    selected_categories = _selected_categories(category)
    if selected_categories:
        filters.append(models.Programme.category.in_(selected_categories))
    if country is not None:
        filters.append(func.lower(models.Programme.country) == country.lower())
    selected_statuses = _selected_statuses(status)
    if selected_statuses:
        filters.append(current_edition.status.in_(selected_statuses))
    selected_fields = _selected_fields(field)
    if selected_fields:
        field_values = cast(
            bindparam(
                "programme_filter_tags",
                value=selected_fields,
                type_=ARRAY(Text()),
            ),
            ARRAY(Text()),
        )
        filters.append(models.Programme.tags.op("?|")(field_values))
    selected_organisers = _selected_organisers(organiser)
    if selected_organisers:
        filters.append(models.Programme.organiser.in_(selected_organisers))
    selected_institution_types = _selected_institution_types(institution_type)
    if selected_institution_types:
        matching_organisers = _organisers_for_institution_types(db, selected_institution_types)
        filters.append(
            models.Programme.organiser.in_(matching_organisers) if matching_organisers else false()
        )

    query_text = (q or "").strip()
    if query_text:
        pattern = _ilike_substring(query_text)
        filters.append(
            or_(
                models.Programme.name.ilike(pattern, escape="\\"),
                models.Programme.organiser.ilike(pattern, escape="\\"),
            )
        )

    total_count = func.count().over().label("total_count")
    selected_tags = _tags_for_divisions(_selected_divisions(divisions))
    match_count = literal(0).label("match_count")
    ordering = [
        func.lower(models.Programme.name).asc(),
        models.Programme.name.asc(),
        models.Programme.id.asc(),
    ]
    if selected_tags:
        tag_values = cast(
            bindparam("programme_match_tags", value=selected_tags, type_=ARRAY(Text())),
            ARRAY(Text()),
        )
        tag_element = (
            func.jsonb_array_elements_text(models.Programme.tags)
            .table_valued("tag")
            .render_derived(name="tag")
        )
        match_count = (
            select(func.count())
            .select_from(tag_element)
            .where(tag_element.c.tag == any_(tag_values))
            .correlate(models.Programme.__table__)
            .scalar_subquery()
            .label("match_count")
        )
        ordering.insert(0, match_count.desc())

    query = (
        select(models.Programme, current_edition, total_count, match_count)
        .outerjoin(
            current_edition,
            and_(
                current_edition.programme_id == models.Programme.id,
                current_edition.year == current_edition_year,
            ),
        )
        .where(*filters)
        .order_by(*ordering)
    )

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).all()
    items = [
        ProgrammeListItem.from_model(
            programme,
            current_edition=edition,
            match_count=match_count,
        )
        for programme, edition, _total, match_count in rows
    ]
    total = rows[0].total_count if rows else 0
    return ProgrammeListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/programme/{slug}", response_model=ProgrammeDetail)
def get_programme(slug: str, db: Session = Depends(get_db)) -> ProgrammeDetail:
    programme = db.scalar(
        select(models.Programme)
        .options(selectinload(models.Programme.editions))
        .where(
            models.Programme.slug == slug,
            models.Programme.is_active.is_(True),
        )
    )
    if programme is None:
        raise HTTPException(status_code=404, detail="Programme not found")
    return ProgrammeDetail.from_model(programme)
