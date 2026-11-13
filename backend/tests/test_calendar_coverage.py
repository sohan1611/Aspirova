"""Offline knowledge-base coverage and the calendar expansion contract."""

from datetime import date
import json

import pytest
from sqlalchemy import func, select, text

from core.hiring_calendar import (
    CALENDAR_META,
    DATA_DIR,
    METADATA,
    ROWS,
    ROLLING_KINDS,
    at_day,
    source_window,
)
from core.models import Programme, ProgrammeEdition
from migrations.versions.b8d1f3a5c7e9_add_government_exam_programme_category import OLD_CATEGORIES
from scripts import calendar_coverage
from scripts.import_calendar import category_for, import_calendar
from scripts.refresh_calendar import refresh_calendar
from scripts.seed_programmes import _seed_with_session
from tests.test_hiring_calendar import programme, request_client, source_programme


def test_all_active_programmes_have_current_or_next_cycle_presence():
    assert calendar_coverage.uncovered_programmes(today=date(2026, 11, 13)) == []


@pytest.mark.parametrize("today", calendar_coverage.FROZEN_DATES)
def test_next_12_months_after_import_and_refresh(engine, today):
    from sqlalchemy.orm import Session

    class SavedPages:
        def fetch(self, url):
            return "inconclusive", None

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        try:
            _seed_with_session(session, current_year=today.year)
            import_calendar(session)
            summary = refresh_calendar(session, SavedPages(), now=at_day(today))
            assert summary["checked"] == len(CALENDAR_META)
            # Each stub fetch is inconclusive. A refresh exception would add
            # another error and expose a failed roll-forward here.
            assert summary["errors"] == len(CALENDAR_META)
            session.expire_all()
            programmes = list(session.scalars(select(Programme)))
            active = [item for item in programmes if item.is_active]
            assert len(active) == 169
            assert calendar_coverage.uncovered_next_12_months(programmes, today=today) == []
            assert calendar_coverage.uncovered_next_12_months(today=today) == []
            edition_count = session.scalar(select(func.count()).select_from(ProgrammeEdition))
            refresh_calendar(session, SavedPages(), now=at_day(today))
            assert (
                session.scalar(select(func.count()).select_from(ProgrammeEdition)) == edition_count
            )
        finally:
            session.close()
            transaction.rollback()


def test_next_12_months_gate_rejects_stale_windows_and_annual_rolling():
    today = date(2027, 3, 1)
    stale = source_programme("jncasr-srfp")
    rolling = source_programme("kaust-vsrp")
    assert calendar_coverage.uncovered_next_12_months([stale, rolling], today=today) == [stale.slug]
    rolling.slug = "jncasr-srfp"
    assert calendar_coverage.uncovered_next_12_months([rolling], today=today) == [rolling.slug]


def test_next_12_months_excludes_the_anniversary_boundary():
    today = date(2026, 11, 13)
    item = programme(opening="2027-11-13", closing="2027-11-14")
    assert calendar_coverage.uncovered_next_12_months([item], today=today) == [item.slug]
    item.editions[0].opens_at = at_day(date(2027, 11, 12))
    assert calendar_coverage.uncovered_next_12_months([item], today=today) == []


@pytest.mark.parametrize("slug", CALENDAR_META)
def test_rolling_classification_and_annual_evidence(slug):
    meta = CALENDAR_META[slug]
    window = source_window(slug)
    if window["rolling"]:
        assert meta["rolling_kind"] in ROLLING_KINDS - {"annual_cycle"}
        assert meta["rolling_reason"].strip()
    if meta.get("rolling_kind") == "annual_cycle":
        assert not window["rolling"]
        assert meta["past_cycle_evidence"]
        assert meta["past_cycle_evidence"] == ROWS[meta["row_id"]]["past_cycle_evidence"]
        for item in meta["past_cycle_evidence"]:
            assert item["source_url"].startswith("https://")
            assert item["cycle"] and item["dates_shown"]
            assert date.fromisoformat(item["source_checked_on"]) == date(2026, 11, 13)
        if window["status"] == "expected":
            for field in ("opens_at", "closes_at"):
                if window[field]:
                    assert window[field.replace("_at", "_precision")] == "month"


def test_coverage_rejects_missing_stale_and_unjustified_rolling(tmp_path, monkeypatch):
    (tmp_path / "programmes.json").write_text(
        json.dumps(
            {
                "programmes": [
                    {"slug": "missing"},
                    {"slug": "stale"},
                    {"slug": "rolling"},
                    {"slug": "retired", "is_active": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(calendar_coverage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        calendar_coverage,
        "CALENDAR_META",
        {"stale": {"cycle_year": 2024}, "rolling": {"cycle_year": 2027}},
    )
    monkeypatch.setattr(
        calendar_coverage,
        "source_window",
        lambda slug: {
            "rolling": slug == "rolling",
            "opens_at": None,
            "closes_at": None,
        },
    )
    assert calendar_coverage.uncovered_programmes(today=date(2026, 11, 13)) == [
        "missing",
        "rolling",
        "stale",
    ]
    calendar_coverage.CALENDAR_META["rolling"]["rolling_reason"] = "Host-specific vacancies."
    calendar_coverage.CALENDAR_META["rolling"]["rolling_kind"] = "vacancy_based"
    assert calendar_coverage.uncovered_programmes(today=date(2026, 11, 13)) == [
        "missing",
        "stale",
    ]


@pytest.mark.parametrize("slug", CALENDAR_META)
def test_every_row_has_provenance_and_application_instructions(slug):
    meta = CALENDAR_META[slug]
    row = ROWS[meta["row_id"]]
    assert row["source_url"].startswith("https://")
    assert date.fromisoformat(row["source_checked_on"])
    assert 2 <= len(row["how_to_apply"].splitlines()) <= 4
    for key in ("how_to_apply", "event_window", "source_url", "source_checked_on"):
        assert meta[key] == row[key]
    if source_window(slug)["rolling"]:
        assert meta["rolling_reason"].strip()
    if category_for(row) == "government_exam":
        assert row["event_window"]


def test_registry_and_import_have_unique_slugs_and_row_ids():
    entries = json.loads((DATA_DIR / "programmes.json").read_text(encoding="utf-8"))["programmes"]
    slugs = [entry["slug"] for entry in entries]
    assert len(slugs) == len(set(slugs))
    ids = [meta["row_id"] for meta in CALENDAR_META.values()]
    assert len(ids) == len(set(ids)) == len(ROWS)
    assert (
        not {
            entry["inactive_programme_slug"]
            for entry in METADATA["watchlist"]
            if entry.get("inactive_programme_slug")
        }
        & CALENDAR_META.keys()
    )


def test_api_returns_application_and_event_metadata_and_null_defaults():
    with request_client([source_programme("upsc-cse"), programme()]) as client:
        result = client.get("/calendar?from=2027-01-01&to=2027-12-31").json()
    exam = next(item for item in result["items"] if item["programme"]["slug"] == "upsc-cse")
    assert exam["metadata"]["how_to_apply"] == CALENDAR_META["upsc-cse"]["how_to_apply"]
    assert "23 May 2027" in exam["metadata"]["event_window"]
    ordinary = next(
        item for item in result["items"] if item["programme"]["slug"] == "test-research"
    )
    assert ordinary["metadata"]["how_to_apply"] is None
    assert ordinary["metadata"]["event_window"] is None


def test_upsc_published_dates_and_ssc_tentative_months():
    assert source_window("upsc-cse")["opens_at"].date() == date(2027, 1, 13)
    assert source_window("upsc-cse")["closes_at"].date() == date(2027, 2, 2)
    for slug in ("ssc-cgl", "ssc-chsl", "ssc-je"):
        window = source_window(slug)
        assert window["status"] == "expected"
        assert window["opens_precision"] == window["closes_precision"] == "month"


def test_unmigrated_database_skips_each_exam_and_imports_every_other_row(engine, caplog):
    from sqlalchemy.orm import Session

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        try:
            session.execute(text("ALTER TABLE programmes DROP CONSTRAINT ck_programmes_category"))
            values = ", ".join(f"'{category}'" for category in OLD_CATEGORIES)
            session.execute(
                text(
                    "ALTER TABLE programmes ADD CONSTRAINT ck_programmes_category "
                    f"CHECK (category IN ({values}))"
                )
            )
            exams = {
                slug: meta
                for slug, meta in CALENDAR_META.items()
                if category_for(ROWS[meta["row_id"]]) == "government_exam"
            }
            assert import_calendar(session) == {
                "imported": len(CALENDAR_META) - len(exams),
                "skipped": len(exams),
            }
            warnings = [
                record.message for record in caplog.records if "skipped by" in record.message
            ]
            assert len(warnings) == len(exams)
            for slug, meta in exams.items():
                assert any(slug in message and meta["row_id"] in message for message in warnings)
            assert session.scalar(select(func.count()).select_from(ProgrammeEdition)) == len(
                CALENDAR_META
            ) - len(exams)
        finally:
            session.close()
            transaction.rollback()


def test_full_registry_import_is_idempotent_and_applies_watchlist(engine):
    from sqlalchemy.orm import Session

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        try:
            _seed_with_session(session, current_year=2026)
            identities = {item.slug: item.id for item in session.scalars(select(Programme))}
            import_calendar(session)
            before = {
                item.id: (item.programme_id, item.year, item.status, item.opens_at, item.closes_at)
                for item in session.scalars(select(ProgrammeEdition))
            }
            import_calendar(session)
            session.expire_all()
            after = {
                item.id: (item.programme_id, item.year, item.status, item.opens_at, item.closes_at)
                for item in session.scalars(select(ProgrammeEdition))
            }
            assert before == after
            for item in session.scalars(select(Programme)):
                if item.slug in identities:
                    assert item.id == identities[item.slug]
            for entry in METADATA["watchlist"]:
                if slug := entry.get("inactive_programme_slug"):
                    assert not session.scalar(
                        select(Programme.is_active).where(Programme.slug == slug)
                    )
        finally:
            session.close()
            transaction.rollback()
