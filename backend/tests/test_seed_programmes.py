import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import models
from scripts import seed_programmes

VALID_CATEGORIES = {
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

REQUIRED_KEYS = {
    "slug",
    "name",
    "organiser",
    "category",
    "url",
    "description",
    "eligibility",
    "typical_window",
    "country",
    "tags",
}

TEST_YEAR = 2026


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _registry_file(tmp_path: Path, *, name: str = "Original Programme") -> Path:
    path = tmp_path / "programmes.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "note": "test registry",
                "programmes": [
                    {
                        "slug": "test-programme-seed",
                        "name": name,
                        "organiser": "Test Organiser",
                        "category": "research_internship",
                        "url": "https://example.edu/programme",
                        "description": "A test research programme.",
                        "eligibility": None,
                        "typical_window": None,
                        "country": "IN",
                        "tags": ["research", "science"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_seed_programmes_is_idempotent(db_session: Session, tmp_path: Path) -> None:
    registry_path = _registry_file(tmp_path)

    seed_programmes.seed(db_session, current_year=TEST_YEAR, registry_path=registry_path)
    seed_programmes.seed(db_session, current_year=TEST_YEAR, registry_path=registry_path)

    programme_count = db_session.scalar(
        select(func.count())
        .select_from(models.Programme)
        .where(models.Programme.slug == "test-programme-seed")
    )
    edition_count = db_session.scalar(
        select(func.count())
        .select_from(models.ProgrammeEdition)
        .join(models.Programme)
        .where(
            models.Programme.slug == "test-programme-seed",
            models.ProgrammeEdition.year == TEST_YEAR,
        )
    )

    assert programme_count == 1
    assert edition_count == 1


def test_seed_programmes_updates_mutable_fields_without_changing_identity(
    db_session: Session, tmp_path: Path
) -> None:
    first_registry = _registry_file(tmp_path, name="Original Programme")
    seed_programmes.seed(db_session, current_year=TEST_YEAR, registry_path=first_registry)

    programme = db_session.scalar(
        select(models.Programme).where(models.Programme.slug == "test-programme-seed")
    )
    assert programme is not None
    original_id = programme.id

    updated_registry = _registry_file(tmp_path, name="Updated Programme")
    seed_programmes.seed(db_session, current_year=TEST_YEAR, registry_path=updated_registry)
    db_session.refresh(programme)

    assert programme.id == original_id
    assert programme.slug == "test-programme-seed"
    assert programme.name == "Updated Programme"


def test_seeded_editions_default_to_expected_with_null_dates(
    db_session: Session, tmp_path: Path
) -> None:
    registry_path = _registry_file(tmp_path)
    seed_programmes.seed(db_session, current_year=TEST_YEAR, registry_path=registry_path)

    edition = db_session.scalar(
        select(models.ProgrammeEdition)
        .join(models.Programme)
        .where(models.Programme.slug == "test-programme-seed")
    )

    assert edition is not None
    assert edition.status == "expected"
    assert edition.opens_at is None
    assert edition.closes_at is None


def test_programme_category_check_rejects_unknown_category(engine) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    try:
        with pytest.raises(IntegrityError):
            connection.execute(text("""
                    insert into programmes
                        (slug, name, organiser, category, url, tags)
                    values
                        ('test-invalid-category', 'Bad', 'Test', 'bad_category',
                         'https://example.edu', '[]'::jsonb)
                    """))
    finally:
        transaction.rollback()
        connection.close()


def test_programme_edition_status_check_rejects_unknown_status(engine) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    try:
        programme_id = connection.execute(text("""
                insert into programmes
                    (slug, name, organiser, category, url, tags)
                values
                    ('test-invalid-status-parent', 'Parent', 'Test',
                     'research_internship', 'https://example.edu', '[]'::jsonb)
                returning id
                """)).scalar_one()

        with pytest.raises(IntegrityError):
            connection.execute(
                text("""
                    insert into programme_editions
                        (programme_id, year, status)
                    values
                        (:programme_id, :year, 'bad_status')
                    """),
                {"programme_id": programme_id, "year": TEST_YEAR},
            )
    finally:
        transaction.rollback()
        connection.close()


def test_programmes_json_is_valid_registry_data() -> None:
    payload = json.loads(seed_programmes.PROGRAMMES_PATH.read_text(encoding="utf-8"))
    programmes = payload["programmes"]
    slugs = [entry["slug"] for entry in programmes]

    assert payload["version"] == 1
    assert len(slugs) == len(set(slugs))

    for entry in programmes:
        assert REQUIRED_KEYS.issubset(entry.keys())
        assert entry["category"] in VALID_CATEGORIES
        assert entry["slug"] == entry["slug"].lower()
        assert " " not in entry["slug"]
        assert entry["tags"]
        assert all(tag == tag.lower() for tag in entry["tags"])
