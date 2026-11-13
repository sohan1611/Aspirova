from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from core.hiring_calendar import (
    CALENDAR_META,
    DATA_DIR,
    IST,
    ROWS,
    calendar_metadata,
    has_rolling_deadline,
)
from core.models import Programme, ProgrammeEdition
from migrations.versions.a7c9e2b4d6f8_add_early_career_programme_category import OLD_CATEGORIES
from pipeline.programme_verification import CalendarPageFetcher, extract_official_calendar_dates
from scripts.import_calendar import _import_row, category_for, import_calendar
from scripts.refresh_calendar import apply_page, refresh_calendar, roll_forward

FIXTURES = Path(__file__).parent / "fixtures" / "calendar"


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


def test_import_idempotent_matches_registry_and_preserves_refresh(db_session):
    existing = Programme(
        slug="iitk-surge",
        name="SURGE",
        organiser="IIT Kanpur",
        category="research_internship",
        url="https://surge.iitk.ac.in/",
        tags=[],
    )
    db_session.add(existing)
    db_session.flush()
    existing_id = existing.id
    assert import_calendar(db_session) == {"imported": len(CALENDAR_META), "skipped": 0}
    assert (
        db_session.scalar(select(Programme.id).where(Programme.slug == "iitk-surge")) == existing_id
    )
    assert existing.name == "SURGE"
    edition = db_session.scalar(
        select(ProgrammeEdition).where(ProgrammeEdition.programme_id == existing_id)
    )
    edition.status = "announced"
    edition.verified_at = datetime(2027, 1, 5, tzinfo=IST)
    db_session.flush()
    before = db_session.scalar(select(func.count()).select_from(ProgrammeEdition))
    assert import_calendar(db_session) == {"imported": len(CALENDAR_META), "skipped": 0}
    assert db_session.scalar(select(func.count()).select_from(ProgrammeEdition)) == before
    assert edition.status == "announced"
    assert db_session.scalar(
        select(func.count()).select_from(Programme).where(Programme.category == "early_career")
    ) == sum(category_for(row) == "early_career" for row in ROWS.values())
    epfl = db_session.scalar(select(Programme).where(Programme.slug == "epfl-life-sciences-srp"))
    assert epfl.editions[0].year == 2027
    assert epfl.editions[0].closes_at.year == 2026


@pytest.mark.parametrize("status", ["announced", "open"])
@pytest.mark.parametrize("verified_day", [13, 14])
def test_authored_closure_overrides_same_day_or_newer_open_edition(
    db_session, status, verified_day
):
    slug = "nic-digital-india-winter"
    meta = CALENDAR_META[slug]
    _import_row(db_session, slug, meta)
    item = db_session.scalar(select(Programme).where(Programme.slug == slug))
    edition = item.editions[0]
    checked = datetime(2026, 11, verified_day, tzinfo=IST)
    edition.status = status
    edition.closes_at = None
    edition.notes = "calendar_deadline_rolling"
    edition.verified_at = checked
    db_session.flush()

    _import_row(db_session, slug, meta)
    assert edition.status == "closed"
    assert edition.closes_at.astimezone(IST).date().isoformat() == "2026-11-13"
    assert "calendar_deadline_rolling" not in edition.notes
    assert edition.verified_at == checked
    before = (edition.status, edition.closes_at, edition.notes, edition.verified_at)
    _import_row(db_session, slug, meta)
    assert (edition.status, edition.closes_at, edition.notes, edition.verified_at) == before


def test_old_category_constraint_skips_tech_and_continues(db_session, caplog):
    # Local transaction only. Restored by the fixture rollback.
    db_session.execute(text("ALTER TABLE programmes DROP CONSTRAINT ck_programmes_category"))
    values = ", ".join(f"'{category}'" for category in OLD_CATEGORIES)
    db_session.execute(
        text(
            f"ALTER TABLE programmes ADD CONSTRAINT ck_programmes_category CHECK (category IN ({values}))"
        )
    )
    summary = import_calendar(db_session)
    skipped = sum(category_for(row) in {"early_career", "government_exam"} for row in ROWS.values())
    assert summary == {"imported": len(CALENDAR_META) - skipped, "skipped": skipped}
    assert (
        len(
            [
                record
                for record in caplog.records
                if "skipped by ck_programmes_category" in record.message
            ]
        )
        == skipped
    )
    assert "OPP-007" in caplog.text
    assert db_session.scalar(select(Programme.id).where(Programme.slug == "kaust-vsrp"))
    assert (
        db_session.scalar(select(func.count()).select_from(ProgrammeEdition))
        == len(CALENDAR_META) - skipped
    )


def test_research_import_reuses_all_five_existing_open_source_programmes(db_session):
    import json

    slugs = {"gsoc", "hacktoberfest", "mlh-fellowship", "outreachy", "lfx-mentorship"}
    registry = json.loads((DATA_DIR / "programmes.json").read_text(encoding="utf-8"))
    existing = {}
    for entry in registry["programmes"]:
        if entry["slug"] not in slugs:
            continue
        item = Programme(
            **{
                key: entry[key]
                for key in (
                    "slug",
                    "name",
                    "organiser",
                    "category",
                    "url",
                    "tags",
                )
            }
        )
        db_session.add(item)
        db_session.flush()
        existing[item.slug] = item.id
    import_calendar(db_session)
    before = {
        item.slug: [
            (
                edition.id,
                edition.year,
                edition.status,
                edition.opens_at,
                edition.closes_at,
                edition.notes,
                edition.verified_at,
            )
            for edition in item.editions
        ]
        for item in db_session.scalars(select(Programme).where(Programme.slug.in_(slugs)))
    }
    import_calendar(db_session)
    db_session.expire_all()
    for slug, programme_id in existing.items():
        items = list(db_session.scalars(select(Programme).where(Programme.slug == slug)))
        assert len(items) == 1
        item = items[0]
        assert item.id == programme_id
        assert item.category == "open_source"
        assert len(item.editions) == 1
        edition = item.editions[0]
        assert edition.year == 2027 and edition.status == "expected"
        assert [
            (
                edition.id,
                edition.year,
                edition.status,
                edition.opens_at,
                edition.closes_at,
                edition.notes,
                edition.verified_at,
            )
        ] == before[slug]


def test_import_matches_existing_name_with_a_different_slug(db_session):
    existing = Programme(
        slug="existing-epfl",
        name="EPFL Life Sciences Summer Research Program 2027",
        organiser="EPFL",
        category="international_research",
        url="https://www.epfl.ch/",
        tags=[],
    )
    db_session.add(existing)
    db_session.flush()
    import_calendar(db_session)
    assert (
        db_session.scalar(select(Programme.id).where(Programme.slug == "epfl-life-sciences-srp"))
        is None
    )
    assert len(existing.editions) == 1


def test_explicit_rolling_call_can_gain_real_dates():
    edition = ProgrammeEdition(year=2027, status="expected")
    html = (FIXTURES / "official.html").read_text()
    assert apply_page(
        edition,
        html,
        now=datetime(2026, 11, 13, tzinfo=IST),
        cycle_start=datetime(2027, 1, 1, tzinfo=IST),
    )
    assert edition.status == "announced"


def test_generic_names_require_matching_organiser(db_session):
    other = Programme(
        slug="jncasr-srfp",
        name="Summer Research Fellowship Programme",
        organiser="JNCASR",
        category="research_internship",
        url="https://www.jncasr.ac.in/",
        tags=[],
    )
    db_session.add(other)
    db_session.flush()
    import_calendar(db_session)
    assert other.organiser == "JNCASR"
    assert calendar_metadata(other.slug, other.name, other.organiser) == CALENDAR_META[other.slug]
    imported = db_session.scalar(select(Programme).where(Programme.slug == "iitd-srfp"))
    assert imported.id != other.id


def test_month_first_iso_and_wrong_cycle_dates():
    html = "<p>2027 applications open: January 10, 2027</p><p>2027 apply by 2027-02-20</p>"
    dates = extract_official_calendar_dates(
        html, cycle_year=2027, cycle_start=datetime(2027, 1, 1, tzinfo=IST)
    )
    assert dates["opens_at"].day == 10
    assert dates["closes_at"].day == 20


def test_import_restores_legacy_openings_after_later_page_checks(db_session):
    import_calendar(db_session)
    checked = datetime(2026, 11, 20, tzinfo=IST)
    restored = []
    for slug, meta in CALENDAR_META.items():
        if not meta.get("deadline_rolling"):
            continue
        item = db_session.scalar(select(Programme).where(Programme.slug == slug))
        edition = item.editions[0]
        if slug != "dpiit-internship":
            edition.opens_at = None
        edition.closes_at = None
        edition.verified_at = checked
        edition.notes = "A later page check found no new dates."
        restored.append((edition, edition.status))
    goldman = db_session.scalar(
        select(Programme).where(Programme.slug == "goldman-sachs-india-summer-analyst")
    )
    future = ProgrammeEdition(programme_id=goldman.id, year=2029, status="expected")
    db_session.add(future)
    db_session.flush()
    import_calendar(db_session)
    for edition, status in restored:
        assert edition.opens_at is not None
        assert edition.closes_at is not None
        assert edition.status == status
        assert edition.verified_at == checked
    assert future.opens_at.year == 2028
    assert future.opens_at.month == 7
    assert future.closes_at.day == 31
    assert future.verified_at is None
    previous = [(edition.opens_at, edition.closes_at, edition.notes) for edition, _ in restored]
    import_calendar(db_session)
    assert [
        (edition.opens_at, edition.closes_at, edition.notes) for edition, _ in restored
    ] == previous


def test_import_preserves_an_existing_verified_cutoff(db_session):
    import_calendar(db_session)
    item = db_session.scalar(select(Programme).where(Programme.slug == "microsoft-swe-india"))
    edition = item.editions[0]
    edition.closes_at = datetime(2027, 10, 15, tzinfo=IST)
    edition.notes = "A human verified this cutoff."
    import_calendar(db_session)
    assert edition.closes_at == datetime(2027, 10, 15, tzinfo=IST)
    assert "calendar_exact_closes_at" in edition.notes


def test_import_repairs_converted_rolling_editions_without_overwriting_discoveries(db_session):
    import_calendar(db_session)
    item = db_session.scalar(select(Programme).where(Programme.slug == "jncasr-srfp"))
    current = item.editions[0]
    current.opens_at = current.closes_at = None
    current.verified_at = datetime(2026, 11, 20, tzinfo=IST)
    current.notes = "Later liveness check, with no verified dates."
    future = ProgrammeEdition(programme_id=item.id, year=2028, status="expected")
    discovered = ProgrammeEdition(
        programme_id=item.id,
        year=2029,
        status="announced",
        closes_at=datetime(2029, 2, 12, tzinfo=IST),
        notes="calendar_exact_closes_at",
    )
    db_session.add_all([future, discovered])
    db_session.flush()
    import_calendar(db_session)
    assert current.opens_at.astimezone(IST).year == 2026
    assert current.closes_at.astimezone(IST).month == 2
    assert current.status == "expected"
    assert current.verified_at == datetime(2026, 11, 20, tzinfo=IST)
    assert future.opens_at.astimezone(IST).year == 2027
    assert future.closes_at.astimezone(IST).year == 2028
    assert discovered.status == "announced"
    assert discovered.opens_at is None
    assert discovered.closes_at == datetime(2029, 2, 12, tzinfo=IST)
    before = [(edition.opens_at, edition.closes_at, edition.notes) for edition in (current, future)]
    import_calendar(db_session)
    assert [
        (edition.opens_at, edition.closes_at, edition.notes) for edition in (current, future)
    ] == before


def test_expired_expected_window_rolls_before_its_intake_year_ends(db_session):
    import_calendar(db_session)
    item = db_session.scalar(select(Programme).where(Programme.slug == "jncasr-srfp"))
    edition = item.editions[0]
    assert edition.year == 2027 and edition.status == "expected"
    now = datetime(2027, 3, 1, tzinfo=IST)
    assert roll_forward(db_session, edition, now=now)
    assert not roll_forward(db_session, edition, now=now)
    future = db_session.scalar(
        select(ProgrammeEdition).where(
            ProgrammeEdition.programme_id == item.id,
            ProgrammeEdition.year == 2028,
        )
    )
    assert future.status == "expected"
    assert future.opens_at.astimezone(IST).date().isoformat() == "2027-11-01"
    assert future.closes_at.astimezone(IST).date().isoformat() == "2028-02-29"
    assert future.source_url == edition.source_url
    assert future.verified_at is None


def test_roll_forward_preserves_rolling_deadline_on_reimport(db_session):
    import_calendar(db_session)
    item = db_session.scalar(
        select(Programme).where(Programme.slug == "goldman-sachs-india-summer-analyst")
    )
    edition = item.editions[0]
    edition.status = "closed"
    assert roll_forward(db_session, edition, now=datetime(2028, 8, 1, tzinfo=IST))
    import_calendar(db_session)
    future = db_session.scalar(
        select(ProgrammeEdition).where(
            ProgrammeEdition.programme_id == item.id,
            ProgrammeEdition.year == 2029,
        )
    )
    assert future.opens_at.astimezone(IST).month == future.closes_at.astimezone(IST).month == 7
    assert has_rolling_deadline(CALENDAR_META[item.slug], future.notes)
    assert "calendar_exact_closes_at" not in future.notes


def test_opening_window_end_does_not_close_a_rolling_deadline():
    edition = ProgrammeEdition(
        year=2027,
        status="open",
        opens_at=datetime(2026, 11, 1, tzinfo=IST),
        closes_at=datetime(2026, 11, 30, 23, 59, 59, tzinfo=IST),
        notes="calendar_deadline_rolling",
    )
    assert not apply_page(
        edition,
        None,
        now=datetime(2026, 12, 1, tzinfo=IST),
        cycle_start=datetime(2026, 1, 1, tzinfo=IST),
        deadline_rolling=True,
    )
    assert edition.status == "open"
    assert apply_page(
        edition,
        (FIXTURES / "official.html").read_text(),
        now=datetime(2027, 3, 1, tzinfo=IST),
        cycle_start=datetime(2026, 1, 1, tzinfo=IST),
        deadline_rolling=True,
    )
    assert edition.status == "closed"
    assert "calendar_exact_closes_at" in edition.notes


def test_fixture_official_promotes_ambiguous_leaves_unchanged():
    edition = ProgrammeEdition(year=2027, status="expected")
    now = datetime(2026, 11, 13, tzinfo=IST)
    start = datetime(2027, 1, 1, tzinfo=IST)
    assert not apply_page(
        edition, (FIXTURES / "ambiguous.html").read_text(), now=now, cycle_start=start
    )
    assert edition.status == "expected"
    assert apply_page(edition, (FIXTURES / "official.html").read_text(), now=now, cycle_start=start)
    assert edition.status == "announced"
    assert edition.opens_at.day == 10
    assert "calendar_exact_opens_at" in edition.notes
    assert apply_page(edition, None, now=datetime(2027, 1, 15, tzinfo=IST), cycle_start=start)
    assert edition.status == "open"
    assert apply_page(edition, None, now=datetime(2027, 3, 1, tzinfo=IST), cycle_start=start)
    assert edition.status == "closed"


def test_prior_calendar_year_is_allowed_only_with_cycle_evidence():
    html = (FIXTURES / "prior-year.html").read_text()
    values = extract_official_calendar_dates(
        html, cycle_year=2027, cycle_start=datetime(2026, 1, 1, tzinfo=IST)
    )
    assert values["closes_at"].year == 2026
    assert not extract_official_calendar_dates(
        html, cycle_year=2028, cycle_start=datetime(2027, 1, 1, tzinfo=IST)
    )


def test_robots_disallow_means_no_page_fetch_and_polite_pacing():
    requests, sleeps = [], []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=(FIXTURES / "robots-disallow.txt").read_text())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = CalendarPageFetcher(client, sleeper=sleeps.append, clock=lambda: 10)
        assert fetcher.fetch("https://example.org/internship") == ("robots_disallowed", None)
        assert requests == ["https://example.org/robots.txt"]
        assert fetcher.fetch("https://example.org/allowed")[0] == "alive"
        assert sleeps == [1]


def test_redirect_rechecks_robots_on_destination():
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.host == "other.org":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://other.org/internship"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert (
            CalendarPageFetcher(client, sleeper=lambda _: None).fetch(
                "https://example.org/internship"
            )[0]
            == "robots_disallowed"
        )
    assert "https://other.org/internship" not in requests


def test_roll_forward_creates_expected_once(db_session):
    import_calendar(db_session)
    programme = db_session.scalar(
        select(Programme).where(Programme.slug == "epfl-life-sciences-srp")
    )
    edition = programme.editions[0]
    edition.status = "closed"
    now = datetime(2026, 11, 16, tzinfo=IST)
    assert roll_forward(db_session, edition, now=now)
    assert not roll_forward(db_session, edition, now=now)
    next_edition = db_session.scalar(
        select(ProgrammeEdition).where(
            ProgrammeEdition.programme_id == programme.id, ProgrammeEdition.year == 2028
        )
    )
    assert next_edition.status == "expected"
    assert next_edition.closes_at.month == 11
    assert next_edition.verified_at is None


def test_refresh_imports_first_and_survives_one_bad_site(db_session):
    class SavedPages:
        def fetch(self, url):
            if "epfl.ch" in url:
                raise ValueError("fixture failure")
            return "alive", (FIXTURES / "ambiguous.html").read_text()

    summary = refresh_calendar(db_session, SavedPages(), now=datetime(2026, 11, 13, tzinfo=IST))
    assert summary["imported"] == len(CALENDAR_META)
    assert summary["checked"] == len(CALENDAR_META)
    assert summary["errors"] == 1
    assert len(CALENDAR_META) == len(ROWS)
