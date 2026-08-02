"""Read API for the curated recurring programmes registry."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from api.deps import get_db
from api.schemas import ProgrammeDetail, ProgrammeListItem, ProgrammeListResponse
from core import models

router = APIRouter()

VALID_PROGRAMME_CATEGORIES = frozenset(
    {
        "research_internship",
        "fellowship",
        "government_internship",
        "open_source",
        "international_research",
        "corporate_research",
        "recurring_competition",
        "scholarship",
        "conference",
    }
)


def _selected_category(category: str | None) -> str | None:
    normalized = (category or "").strip().lower()
    if not normalized:
        return None
    if normalized not in VALID_PROGRAMME_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid category")
    return normalized


def _ilike_substring(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/programmes", response_model=ProgrammeListResponse)
def list_programmes(
    category: str | None = Query(None, max_length=64),
    country: str | None = Query(None, min_length=2, max_length=2),
    status: str | None = Query(None, pattern="^(expected|announced|open|closed)$"),
    q: str | None = Query(None, max_length=200),
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
    selected_category = _selected_category(category)
    if selected_category is not None:
        filters.append(models.Programme.category == selected_category)
    if country is not None:
        filters.append(func.lower(models.Programme.country) == country.lower())
    if status is not None:
        filters.append(current_edition.status == status)

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
    query = (
        select(models.Programme, current_edition, total_count)
        .outerjoin(
            current_edition,
            and_(
                current_edition.programme_id == models.Programme.id,
                current_edition.year == current_edition_year,
            ),
        )
        .where(*filters)
        .order_by(
            func.lower(models.Programme.name).asc(),
            models.Programme.name.asc(),
            models.Programme.id.asc(),
        )
    )

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).all()
    items = [
        ProgrammeListItem.from_model(programme, current_edition=edition)
        for programme, edition, _total in rows
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
