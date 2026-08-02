"""Seed the curated recurring-programmes registry.

Idempotent - safe to re-run. Usage: uv run python -m scripts.seed_programmes
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Programme, ProgrammeEdition

PROGRAMMES_PATH = Path(__file__).resolve().parents[1] / "data" / "programmes.json"
PROGRAMME_EDITIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "programme_editions.json"

MUTABLE_PROGRAMME_FIELDS = (
    "name",
    "organiser",
    "category",
    "url",
    "description",
    "eligibility",
    "typical_window",
    "country",
    "tags",
)
MUTABLE_AUTHORED_EDITION_FIELDS = (
    "status",
    "opens_at",
    "closes_at",
    "source_url",
    "verified_at",
    "notes",
)
AUTHORED_EDITION_STATUSES = frozenset({"expected", "announced", "closed", "discontinued"})


def _load_programmes(path: Path = PROGRAMMES_PATH) -> list[Mapping[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["programmes"]


def _load_programme_editions(
    path: Path = PROGRAMME_EDITIONS_PATH,
) -> list[Mapping[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["editions"]


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_authored_editions(
    editions: list[Mapping[str, Any]],
) -> None:
    for entry in editions:
        status = entry.get("status")
        if status == "open":
            raise ValueError(
                "programme_editions.json must not contain status 'open'; "
                "only a deliberate database action may mark an edition open"
            )
        if status not in AUTHORED_EDITION_STATUSES:
            raise ValueError(
                "programme_editions.json contains unsupported status "
                f"{status!r}; expected one of "
                f"{sorted(AUTHORED_EDITION_STATUSES)}"
            )


def _validate_authored_programme_slugs(
    session: Session,
    *,
    programmes: list[Mapping[str, Any]],
    editions: list[Mapping[str, Any]],
) -> None:
    authored_slugs = {entry["programme_slug"] for entry in editions}
    if not authored_slugs:
        return

    registry_slugs = {entry["slug"] for entry in programmes}
    existing_slugs = set(
        session.scalars(select(Programme.slug).where(Programme.slug.in_(authored_slugs)))
    )
    missing_slugs = sorted(authored_slugs - registry_slugs - existing_slugs)
    if missing_slugs:
        raise ValueError(
            "programme_editions.json references unknown programme_slug: "
            f"{', '.join(missing_slugs)}"
        )


def _authored_edition_values(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": entry["status"],
        "opens_at": _parse_datetime(entry.get("opens_at")),
        "closes_at": _parse_datetime(entry.get("closes_at")),
        "source_url": entry.get("source_url"),
        "verified_at": _parse_datetime(entry.get("verified_at")),
        "notes": entry.get("notes"),
    }


def _apply_authored_editions(
    session: Session,
    editions: list[Mapping[str, Any]],
) -> tuple[int, int]:
    created, updated = 0, 0

    for entry in editions:
        programme = session.scalar(
            select(Programme).where(Programme.slug == entry["programme_slug"])
        )
        if programme is None:
            raise ValueError(
                "programme_editions.json references unknown programme_slug: "
                f"{entry['programme_slug']}"
            )

        values = _authored_edition_values(entry)
        edition = session.scalar(
            select(ProgrammeEdition).where(
                ProgrammeEdition.programme_id == programme.id,
                ProgrammeEdition.year == entry["year"],
            )
        )
        if edition is None:
            session.add(
                ProgrammeEdition(
                    programme_id=programme.id,
                    year=entry["year"],
                    **values,
                )
            )
            created += 1
            continue

        changed = False
        for field in MUTABLE_AUTHORED_EDITION_FIELDS:
            next_value = values[field]
            if getattr(edition, field) != next_value:
                setattr(edition, field, next_value)
                changed = True
        if changed:
            updated += 1

    return created, updated


def _seed_with_session(
    session: Session,
    *,
    current_year: int,
    registry_path: Path = PROGRAMMES_PATH,
    edition_registry_path: Path = PROGRAMME_EDITIONS_PATH,
) -> tuple[int, int, int, int, int]:
    created, updated, editions_created = 0, 0, 0
    programmes = _load_programmes(registry_path)
    authored_editions = _load_programme_editions(edition_registry_path)
    _validate_authored_editions(authored_editions)
    _validate_authored_programme_slugs(
        session,
        programmes=programmes,
        editions=authored_editions,
    )

    for entry in programmes:
        programme = session.scalar(select(Programme).where(Programme.slug == entry["slug"]))
        if programme is None:
            programme = Programme(
                slug=entry["slug"],
                name=entry["name"],
                organiser=entry["organiser"],
                category=entry["category"],
                url=entry["url"],
                description=entry.get("description"),
                eligibility=entry.get("eligibility"),
                typical_window=entry.get("typical_window"),
                country=entry.get("country"),
                tags=entry["tags"],
            )
            session.add(programme)
            session.flush()
            created += 1
        else:
            changed = False
            for field in MUTABLE_PROGRAMME_FIELDS:
                next_value = entry.get(field)
                if getattr(programme, field) != next_value:
                    setattr(programme, field, next_value)
                    changed = True
            if changed:
                programme.updated_at = datetime.now(UTC)
                updated += 1

        edition = session.scalar(
            select(ProgrammeEdition).where(
                ProgrammeEdition.programme_id == programme.id,
                ProgrammeEdition.year == current_year,
            )
        )
        if edition is None:
            session.add(
                ProgrammeEdition(
                    programme_id=programme.id,
                    year=current_year,
                    status="expected",
                    opens_at=None,
                    closes_at=None,
                )
            )
            editions_created += 1

    authored_created, authored_updated = _apply_authored_editions(
        session,
        authored_editions,
    )
    return created, updated, editions_created, authored_created, authored_updated


def seed(
    session: Session | None = None,
    *,
    current_year: int | None = None,
    registry_path: Path = PROGRAMMES_PATH,
    edition_registry_path: Path = PROGRAMME_EDITIONS_PATH,
) -> tuple[int, int, int, int, int]:
    year = current_year if current_year is not None else datetime.now(UTC).year

    if session is not None:
        summary = _seed_with_session(
            session,
            current_year=year,
            registry_path=registry_path,
            edition_registry_path=edition_registry_path,
        )
        session.flush()
    else:
        engine = make_engine()
        with Session(engine) as managed_session:
            summary = _seed_with_session(
                managed_session,
                current_year=year,
                registry_path=registry_path,
                edition_registry_path=edition_registry_path,
            )
            managed_session.commit()

    created, updated, editions_created, authored_created, authored_updated = summary
    print(
        "programmes: "
        f"{created} created, {updated} updated; "
        f"editions: {editions_created} default created, "
        f"{authored_created} authored created, "
        f"{authored_updated} authored updated"
    )
    return summary


if __name__ == "__main__":
    seed()
