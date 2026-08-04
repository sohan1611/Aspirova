import json
import re
from datetime import UTC, datetime
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

# These are organiser/location/type signals, not field-of-study signals.
# Mapping them would match nearly the whole registry and destroy ranking value.
REGISTRY_ONLY_TAGS = {
    "research",
    "international",
    "government",
    "competition",
    "open-source",
}

TEST_YEAR = 2026
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


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


def _edition_registry_file(
    tmp_path: Path,
    editions: list[dict],
) -> Path:
    path = tmp_path / "programme_editions.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "note": "test edition registry",
                "editions": editions,
            }
        ),
        encoding="utf-8",
    )
    return path


def _programmes_registry_entries() -> list[dict]:
    payload = json.loads(seed_programmes.PROGRAMMES_PATH.read_text(encoding="utf-8"))
    return payload["programmes"]


def _allowed_programme_tags() -> set[str]:
    tag_map_path = seed_programmes.PROGRAMMES_PATH.with_name("programme_tag_map.json")
    tag_map = json.loads(tag_map_path.read_text(encoding="utf-8"))
    mapped_tags: set[str] = set()
    for tags in tag_map["divisions"].values():
        mapped_tags.update(tags)
    return mapped_tags | REGISTRY_ONLY_TAGS


def test_seed_programmes_is_idempotent(db_session: Session, tmp_path: Path) -> None:
    registry_path = _registry_file(tmp_path)
    edition_registry_path = _edition_registry_file(tmp_path, [])

    seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=registry_path,
        edition_registry_path=edition_registry_path,
    )
    seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=registry_path,
        edition_registry_path=edition_registry_path,
    )

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
    edition_registry_path = _edition_registry_file(tmp_path, [])
    seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=first_registry,
        edition_registry_path=edition_registry_path,
    )

    programme = db_session.scalar(
        select(models.Programme).where(models.Programme.slug == "test-programme-seed")
    )
    assert programme is not None
    original_id = programme.id

    updated_registry = _registry_file(tmp_path, name="Updated Programme")
    seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=updated_registry,
        edition_registry_path=edition_registry_path,
    )
    db_session.refresh(programme)

    assert programme.id == original_id
    assert programme.slug == "test-programme-seed"
    assert programme.name == "Updated Programme"


def test_seeded_editions_default_to_expected_with_null_dates(
    db_session: Session, tmp_path: Path
) -> None:
    registry_path = _registry_file(tmp_path)
    edition_registry_path = _edition_registry_file(tmp_path, [])
    seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=registry_path,
        edition_registry_path=edition_registry_path,
    )

    edition = db_session.scalar(
        select(models.ProgrammeEdition)
        .join(models.Programme)
        .where(models.Programme.slug == "test-programme-seed")
    )

    assert edition is not None
    assert edition.status == "expected"
    assert edition.opens_at is None
    assert edition.closes_at is None


def test_seed_authored_editions_is_idempotent_and_updates_expected_in_place(
    db_session: Session,
    tmp_path: Path,
) -> None:
    registry_path = _registry_file(tmp_path)
    edition_registry_path = _edition_registry_file(
        tmp_path,
        [
            {
                "programme_slug": "test-programme-seed",
                "year": TEST_YEAR,
                "status": "closed",
                "source_url": "https://example.edu/programme/2026",
                "verified_at": "2026-08-02T00:00:00Z",
                "notes": "Official call is closed.",
            }
        ],
    )

    first = seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=registry_path,
        edition_registry_path=edition_registry_path,
    )
    second = seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=registry_path,
        edition_registry_path=edition_registry_path,
    )

    edition = db_session.scalar(
        select(models.ProgrammeEdition)
        .join(models.Programme)
        .where(
            models.Programme.slug == "test-programme-seed",
            models.ProgrammeEdition.year == TEST_YEAR,
        )
    )

    assert first == (1, 0, 1, 0, 1)
    assert second == (0, 0, 0, 0, 0)
    assert edition is not None
    assert edition.status == "closed"
    assert edition.opens_at is None
    assert edition.closes_at is None
    assert edition.source_url == "https://example.edu/programme/2026"
    assert edition.verified_at == datetime(2026, 8, 2, tzinfo=UTC)
    assert edition.notes == "Official call is closed."


def test_seed_authored_editions_rejects_open_and_writes_nothing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    registry_path = _registry_file(tmp_path)
    edition_registry_path = _edition_registry_file(
        tmp_path,
        [
            {
                "programme_slug": "test-programme-seed",
                "year": TEST_YEAR,
                "status": "open",
            }
        ],
    )

    with pytest.raises(ValueError, match="status 'open'"):
        seed_programmes.seed(
            db_session,
            current_year=TEST_YEAR,
            registry_path=registry_path,
            edition_registry_path=edition_registry_path,
        )

    programme_count = db_session.scalar(
        select(func.count())
        .select_from(models.Programme)
        .where(models.Programme.slug == "test-programme-seed")
    )
    edition_count = db_session.scalar(
        select(func.count())
        .select_from(models.ProgrammeEdition)
        .join(models.Programme)
        .where(models.Programme.slug == "test-programme-seed")
    )

    assert programme_count == 0
    assert edition_count == 0


def test_seed_authored_editions_leave_absent_db_editions_untouched(
    db_session: Session,
    tmp_path: Path,
) -> None:
    registry_path = _registry_file(tmp_path)
    empty_editions_path = _edition_registry_file(tmp_path, [])
    seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=registry_path,
        edition_registry_path=empty_editions_path,
    )

    programme = db_session.scalar(
        select(models.Programme).where(models.Programme.slug == "test-programme-seed")
    )
    assert programme is not None
    untouched_opens_at = datetime(2026, 10, 1, tzinfo=UTC)
    untouched_closes_at = datetime(2026, 10, 31, tzinfo=UTC)
    untouched_verified_at = datetime(2026, 7, 1, tzinfo=UTC)
    untouched = models.ProgrammeEdition(
        programme_id=programme.id,
        year=TEST_YEAR + 1,
        status="announced",
        opens_at=untouched_opens_at,
        closes_at=untouched_closes_at,
        source_url="https://example.edu/programme/untouched",
        verified_at=untouched_verified_at,
        notes="Do not edit this row.",
    )
    db_session.add(untouched)
    db_session.flush()

    authored_path = _edition_registry_file(
        tmp_path,
        [
            {
                "programme_slug": "test-programme-seed",
                "year": TEST_YEAR,
                "status": "closed",
                "source_url": "https://example.edu/programme/2026",
                "verified_at": "2026-08-02T00:00:00Z",
                "notes": "Closed edition.",
            }
        ],
    )
    seed_programmes.seed(
        db_session,
        current_year=TEST_YEAR,
        registry_path=registry_path,
        edition_registry_path=authored_path,
    )
    db_session.refresh(untouched)

    assert untouched.status == "announced"
    assert untouched.opens_at == untouched_opens_at
    assert untouched.closes_at == untouched_closes_at
    assert untouched.source_url == "https://example.edu/programme/untouched"
    assert untouched.verified_at == untouched_verified_at
    assert untouched.notes == "Do not edit this row."


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


def test_programmes_json_review_months_are_valid_when_present() -> None:
    for entry in _programmes_registry_entries():
        if "review_months" not in entry:
            continue

        review_months = entry["review_months"]
        assert isinstance(
            review_months, list
        ), f"programme {entry['slug']} review_months must be a list"
        assert review_months, f"programme {entry['slug']} review_months must not be empty"
        assert all(
            type(month) is int for month in review_months
        ), f"programme {entry['slug']} review_months must contain only integers"
        assert all(
            1 <= month <= 12 for month in review_months
        ), f"programme {entry['slug']} review_months must be between 1 and 12"
        assert len(review_months) == len(
            set(review_months)
        ), f"programme {entry['slug']} review_months must not contain duplicates"


def test_programmes_json_tags_use_closed_vocabulary() -> None:
    allowed_tags = _allowed_programme_tags()

    for entry in _programmes_registry_entries():
        for tag in entry["tags"]:
            assert tag in allowed_tags, f"programme {entry['slug']} uses unknown tag {tag!r}"


def test_programmes_json_urls_are_unique_and_https() -> None:
    seen_urls: set[str] = set()

    for entry in _programmes_registry_entries():
        url = entry["url"]
        assert url.startswith(
            "https://"
        ), f"programme {entry['slug']} url must start with https://: {url}"
        assert url not in seen_urls, f"programme {entry['slug']} duplicates url {url}"
        seen_urls.add(url)


def test_programmes_json_country_codes_fit_db_column() -> None:
    for entry in _programmes_registry_entries():
        country = entry.get("country")
        assert country is None or (
            isinstance(country, str)
            and len(country) == 2
            and country.isalpha()
            and country.isupper()
        ), f"programme {entry['slug']} has invalid country {country!r}"


def test_programmes_json_rendered_fields_are_present_strings() -> None:
    # description and typical_window are what the directory CARD renders, so a
    # blank one is a visible defect and the registry's core value ("shows dormant
    # programmes with their typical windows") is lost.
    for entry in _programmes_registry_entries():
        for field in ("description", "typical_window"):
            value = entry.get(field)
            assert (
                isinstance(value, str) and value.strip()
            ), f"programme {entry['slug']} has blank or non-string {field}"


def test_programmes_json_eligibility_is_absent_or_meaningful() -> None:
    # eligibility is a detail-page section that degrades gracefully when absent,
    # so null is allowed: 20 curated entries have no verified eligibility text and
    # inventing it would be exactly the fabrication the honesty rule forbids.
    # What is NOT allowed is a present-but-empty value, which renders an empty
    # section rather than omitting it.
    for entry in _programmes_registry_entries():
        eligibility = entry.get("eligibility")
        assert eligibility is None or (
            isinstance(eligibility, str) and eligibility.strip()
        ), f"programme {entry['slug']} has a present but blank eligibility"


def test_programmes_json_typical_window_has_no_specific_year() -> None:
    for entry in _programmes_registry_entries():
        typical_window = entry.get("typical_window")
        assert isinstance(
            typical_window, str
        ), f"programme {entry['slug']} has non-string typical_window"
        match = YEAR_PATTERN.search(typical_window)
        assert match is None, (
            f"programme {entry['slug']} typical_window contains year " f"{match.group(0)}"
        )


def test_programmes_json_represents_every_valid_category() -> None:
    represented_categories = {entry["category"] for entry in _programmes_registry_entries()}
    missing_categories = VALID_CATEGORIES - represented_categories

    assert not missing_categories, (
        "programmes.json has no programme for categories: "
        f"{', '.join(sorted(missing_categories))}"
    )
