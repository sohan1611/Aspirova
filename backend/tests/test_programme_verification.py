"""Programme registry verification coverage."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from pipeline.programme_verification import (
    extract_months_from_typical_window,
    typical_window_needs_review,
    verify_programmes,
)


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


def _programme(
    db_session: Session,
    *,
    suffix: str,
    name: str,
    typical_window: str | None = None,
    is_active: bool = True,
) -> models.Programme:
    programme = models.Programme(
        slug=f"programme-verification-{name}-{suffix}",
        name=f"Programme Verification {name} {suffix}",
        organiser="Programme Verification Org",
        category="research_internship",
        url=f"https://example.com/programme-verification/{name}/{suffix}",
        description="Test programme.",
        eligibility="Students.",
        typical_window=typical_window,
        country="IN",
        tags=["verification"],
        is_active=is_active,
    )
    db_session.add(programme)
    db_session.flush()
    return programme


def _edition(
    db_session: Session,
    programme: models.Programme,
    *,
    year: int,
    status: str = "expected",
    opens_at: datetime | None = None,
    closes_at: datetime | None = None,
    verified_at: datetime | None = None,
) -> models.ProgrammeEdition:
    edition = models.ProgrammeEdition(
        programme_id=programme.id,
        year=year,
        status=status,
        opens_at=opens_at,
        closes_at=closes_at,
        source_url=f"{programme.url}/{year}",
        verified_at=verified_at,
    )
    db_session.add(edition)
    db_session.flush()
    return edition


def _programme_slugs(items) -> set[str]:
    return {item.programme_slug for item in items}


def _edition_slugs(items) -> set[str]:
    return {item.programme_slug for item in items}


def test_typical_window_month_extractor_is_conservative() -> None:
    assert extract_months_from_typical_window("applications usually open in February") == {2}
    assert extract_months_from_typical_window("FEB application window") == {2}
    assert extract_months_from_typical_window("March shortlist, Apr interviews") == {3, 4}
    assert extract_months_from_typical_window("host-specific rolling deadlines") == set()
    assert extract_months_from_typical_window("marching orders from a janitor") == set()


def test_typical_window_needs_review_matches_current_or_previous_month() -> None:
    now = datetime(2026, 4, 15, tzinfo=UTC)

    assert typical_window_needs_review("applications usually open in April", now=now)
    assert typical_window_needs_review("applications usually open in Mar", now=now)
    assert not typical_window_needs_review("applications usually open in May", now=now)
    assert not typical_window_needs_review("host-specific rolling deadlines", now=now)


def test_programme_verification_report_buckets_populate(db_session: Session) -> None:
    now = datetime(2026, 4, 15, 12, tzinfo=UTC)
    suffix = uuid.uuid4().hex

    dead = _programme(
        db_session,
        suffix=suffix,
        name="dead",
        typical_window="applications usually open in November",
    )
    _edition(db_session, dead, year=now.year, verified_at=now)
    alive = _programme(
        db_session,
        suffix=suffix,
        name="alive",
        typical_window="applications usually open in November",
    )
    _edition(db_session, alive, year=now.year, verified_at=now)
    inconclusive = _programme(
        db_session,
        suffix=suffix,
        name="inconclusive",
        typical_window="applications usually open in November",
    )
    _edition(db_session, inconclusive, year=now.year, verified_at=now)
    window = _programme(
        db_session,
        suffix=suffix,
        name="window",
        typical_window="applications usually open in March",
    )
    _edition(db_session, window, year=now.year, status="expected", verified_at=now)
    stale = _programme(
        db_session,
        suffix=suffix,
        name="stale",
        typical_window="applications usually open in August",
    )
    _edition(db_session, stale, year=now.year, status="closed", verified_at=None)
    old = _programme(
        db_session,
        suffix=suffix,
        name="old",
        typical_window="applications usually open in August",
    )
    _edition(
        db_session,
        old,
        year=now.year,
        status="closed",
        verified_at=now - timedelta(days=91),
    )
    overdue = _programme(
        db_session,
        suffix=suffix,
        name="overdue",
        typical_window="applications usually open in August",
    )
    _edition(
        db_session,
        overdue,
        year=now.year,
        status="open",
        closes_at=now - timedelta(days=1),
        verified_at=now,
    )
    missing = _programme(
        db_session,
        suffix=suffix,
        name="missing",
        typical_window="applications usually open in August",
    )
    _edition(db_session, missing, year=now.year - 1, status="closed", verified_at=now)

    decisions = {
        dead.url: "closed",
        alive.url: "alive",
        inconclusive.url: "inconclusive",
    }
    report = verify_programmes(
        db_session,
        apply=False,
        limit=5000,
        max_seconds=60,
        now=now,
        checker=lambda url: decisions.get(url, "inconclusive"),
    )

    assert dead.slug in _programme_slugs(report.dead_urls)
    assert inconclusive.slug not in _programme_slugs(report.dead_urls)
    assert window.slug in _edition_slugs(report.window_arrived)
    assert stale.slug in _edition_slugs(report.stale_verification)
    assert old.slug in _edition_slugs(report.stale_verification)
    assert overdue.slug in _edition_slugs(report.overdue_close)
    assert missing.slug in _programme_slugs(report.missing_current_year_edition)
    assert report.closed_updated == 0


def test_closing_transition_only_applies_to_past_non_null_closes_at(
    db_session: Session,
) -> None:
    now = datetime(2026, 5, 10, 12, tzinfo=UTC)
    suffix = uuid.uuid4().hex

    past_open = _programme(db_session, suffix=suffix, name="past-open")
    _edition(
        db_session,
        past_open,
        year=now.year,
        status="open",
        closes_at=now - timedelta(seconds=1),
        verified_at=None,
    )
    past_announced = _programme(db_session, suffix=suffix, name="past-announced")
    _edition(
        db_session,
        past_announced,
        year=now.year,
        status="announced",
        closes_at=now - timedelta(days=1),
        verified_at=None,
    )
    null_close = _programme(db_session, suffix=suffix, name="null-close")
    _edition(
        db_session,
        null_close,
        year=now.year,
        status="open",
        closes_at=None,
        verified_at=None,
    )
    future_close = _programme(db_session, suffix=suffix, name="future-close")
    _edition(
        db_session,
        future_close,
        year=now.year,
        status="announced",
        closes_at=now + timedelta(days=1),
        verified_at=None,
    )
    expected_past = _programme(db_session, suffix=suffix, name="expected-past")
    _edition(
        db_session,
        expected_past,
        year=now.year,
        status="expected",
        closes_at=now - timedelta(days=1),
        verified_at=None,
    )

    report = verify_programmes(
        db_session,
        apply=True,
        limit=5000,
        max_seconds=60,
        now=now,
        checker=lambda _url: "alive",
    )
    db_session.expire_all()

    rows = {
        slug: (status, verified_at)
        for slug, status, verified_at in db_session.execute(
            select(
                models.Programme.slug,
                models.ProgrammeEdition.status,
                models.ProgrammeEdition.verified_at,
            )
            .join(
                models.ProgrammeEdition,
                models.ProgrammeEdition.programme_id == models.Programme.id,
            )
            .where(
                models.Programme.slug.in_(
                    [
                        past_open.slug,
                        past_announced.slug,
                        null_close.slug,
                        future_close.slug,
                        expected_past.slug,
                    ]
                )
            )
        ).all()
    }

    assert past_open.slug in _edition_slugs(report.overdue_close)
    assert past_announced.slug in _edition_slugs(report.overdue_close)
    assert rows[past_open.slug] == ("closed", now)
    assert rows[past_announced.slug] == ("closed", now)
    assert rows[null_close.slug] == ("open", None)
    assert rows[future_close.slug] == ("announced", None)
    assert rows[expected_past.slug] == ("expected", None)


def test_dry_run_does_not_mutate_overdue_editions(db_session: Session) -> None:
    now = datetime(2026, 6, 1, 12, tzinfo=UTC)
    suffix = uuid.uuid4().hex
    programme = _programme(db_session, suffix=suffix, name="dry-run")
    _edition(
        db_session,
        programme,
        year=now.year,
        status="open",
        closes_at=now - timedelta(days=1),
        verified_at=None,
    )

    report = verify_programmes(
        db_session,
        apply=False,
        limit=5000,
        max_seconds=60,
        now=now,
        checker=lambda _url: "alive",
    )
    db_session.expire_all()

    status, verified_at = db_session.execute(
        select(models.ProgrammeEdition.status, models.ProgrammeEdition.verified_at)
        .join(models.Programme, models.Programme.id == models.ProgrammeEdition.programme_id)
        .where(models.Programme.slug == programme.slug)
    ).one()
    assert programme.slug in _edition_slugs(report.overdue_close)
    assert report.closed_updated == 0
    assert status == "open"
    assert verified_at is None


def test_programme_verification_never_promotes_to_open(db_session: Session) -> None:
    now = datetime(2026, 4, 15, 12, tzinfo=UTC)
    suffix = uuid.uuid4().hex
    expected = _programme(
        db_session,
        suffix=suffix,
        name="expected-window",
        typical_window="applications usually open in April",
    )
    _edition(
        db_session,
        expected,
        year=now.year,
        status="expected",
        opens_at=now - timedelta(days=3),
        closes_at=now + timedelta(days=3),
        verified_at=None,
    )
    announced = _programme(db_session, suffix=suffix, name="announced-future")
    _edition(
        db_session,
        announced,
        year=now.year,
        status="announced",
        opens_at=now + timedelta(days=1),
        closes_at=now + timedelta(days=10),
        verified_at=None,
    )

    verify_programmes(
        db_session,
        apply=True,
        limit=5000,
        max_seconds=60,
        now=now,
        checker=lambda _url: "closed",
    )
    db_session.expire_all()

    statuses = set(
        db_session.scalars(
            select(models.ProgrammeEdition.status)
            .join(models.Programme, models.Programme.id == models.ProgrammeEdition.programme_id)
            .where(models.Programme.slug.in_([expected.slug, announced.slug]))
        ).all()
    )
    assert statuses == {"expected", "announced"}
    assert "open" not in statuses
