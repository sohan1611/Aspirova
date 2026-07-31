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


def _load_programmes(path: Path = PROGRAMMES_PATH) -> list[Mapping[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["programmes"]


def _seed_with_session(
    session: Session,
    *,
    current_year: int,
    registry_path: Path = PROGRAMMES_PATH,
) -> tuple[int, int, int]:
    created, updated, editions_created = 0, 0, 0

    for entry in _load_programmes(registry_path):
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
        elif edition.status == "expected":
            edition.opens_at = None
            edition.closes_at = None

    return created, updated, editions_created


def seed(
    session: Session | None = None,
    *,
    current_year: int | None = None,
    registry_path: Path = PROGRAMMES_PATH,
) -> tuple[int, int, int]:
    year = current_year if current_year is not None else datetime.now(UTC).year

    if session is not None:
        summary = _seed_with_session(session, current_year=year, registry_path=registry_path)
        session.flush()
    else:
        engine = make_engine()
        with Session(engine) as managed_session:
            summary = _seed_with_session(
                managed_session,
                current_year=year,
                registry_path=registry_path,
            )
            managed_session.commit()

    created, updated, editions_created = summary
    print(
        "programmes: "
        f"{created} created, {updated} updated; "
        f"editions: {editions_created} created"
    )
    return summary


if __name__ == "__main__":
    seed()
