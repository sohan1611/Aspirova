"""CAL-04: small, transactional Postgres fixtures, never production data."""

from dataclasses import FrozenInstanceError
from datetime import date, datetime
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session

from api import calendar as calendar_api, middleware
from api.deps import get_db
from core import calendar_public, hiring_calendar as source
from core.calendar_reconciliation import (
    metadata_gaps,
    reconcile_calendar,
)
from core.config import get_settings
from core.models import Programme, ProgrammeEdition
from core.programme_labels import PROGRAMME_CATEGORY_LABELS
from scripts import import_calendar as importer, refresh_calendar as refresh

TODAY = date(2026, 11, 17)


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        try:
            session.execute(delete(Programme))
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def small_source(monkeypatch):
    names = (
        "dated",
        "rolling",
        "past",
        "future",
        "closed",
        "retired",
        "skipped",
        "pending",
        "unexplained",
        "recurring",
        "visible-closed",
        "inactive",
    )
    base_row = next(iter(source.ROWS.values()))
    rows, metadata = {}, {}
    for name in names:
        row_id, slug = f"ROW-{name}", f"cal-{name}"
        rows[row_id] = {
            **base_row,
            "id": row_id,
            "opportunity": name,
            "application_open": "Jan 2027",
            "registration_deadline": "Feb 2027",
            "category": "government_exam" if name == "skipped" else "research_internship",
            "geography": "India",
        }
        metadata[slug] = {
            "row_id": row_id,
            "name": name,
            "organiser": "Calendar fixture",
            "cycle_year": 2027,
            "source_url": "https://example.org/calendar",
        }
    rows["ROW-rolling"].update(application_open="Rolling", registration_deadline="Rolling")
    metadata["cal-rolling"].update(rolling_kind="always_open", rolling_reason="Year round")
    metadata["cal-recurring"]["recurrence"] = {
        "basis": "official monthly rule",
        "precision": "day",
        "windows": [
            {"open_month": month, "close_month": month, "open_day": 1, "close_day": 10}
            for month in range(1, 13)
        ],
    }
    source_data = {"opportunities": list(rows.values())}
    sidecar = {
        "programmes": metadata,
        "overrides": {},
        "watchlist": [{"inactive_programme_slug": "cal-retired"}],
    }
    for module in (source, importer, calendar_public):
        for key, value in {
            "ROWS": rows,
            "CALENDAR_META": metadata,
            "SOURCE": source_data,
            "METADATA": sidecar,
            "SLUG_BY_ROW_ID": {meta["row_id"]: slug for slug, meta in metadata.items()},
            "META_BY_NAME": {
                (meta["name"].casefold(), meta["organiser"].casefold()): meta
                for meta in metadata.values()
            },
        }.items():
            if hasattr(module, key):
                monkeypatch.setattr(module, key, value)
    return metadata


@pytest.fixture
def seeded(db_session, small_source):
    for slug, meta in small_source.items():
        name = meta["name"]
        if name in {"skipped", "pending"}:
            continue
        opening, closing, status = date(2027, 1, 1), date(2027, 2, 28), "expected"
        if name in {"past", "closed"}:
            opening, closing = date(2026, 1, 1), date(2026, 2, 28)
        if name == "future":
            opening, closing = date(2028, 1, 1), date(2028, 2, 28)
        if name in {"closed", "visible-closed"}:
            status = "closed"
        item = Programme(
            # Import preserves a canonical registry slug matched by name/organiser.
            slug="registry-alias" if name == "dated" else slug,
            name=name,
            organiser=meta["organiser"],
            category="research_internship",
            url="https://example.org/calendar",
            tags=[],
            is_active=name != "inactive",
            editions=(
                []
                if name == "unexplained"
                else [
                    ProgrammeEdition(
                        year=2027,
                        status=status,
                        opens_at=None if name == "rolling" else source.at_day(opening),
                        closes_at=None if name == "rolling" else source.at_day(closing, end=True),
                    )
                ]
            ),
        )
        db_session.add(item)
    db_session.add(
        Programme(
            slug="registry-only",
            name="Other registry programme",
            organiser="Other",
            category="research_internship",
            url="https://example.org/other",
            tags=[],
            editions=[
                ProgrammeEdition(
                    year=2027,
                    status="expected",
                    opens_at=source.at_day(date(2027, 1, 1)),
                    closes_at=source.at_day(date(2027, 2, 28), end=True),
                )
            ],
        )
    )
    db_session.flush()
    # Simulate a pre-government-exam migration schema, inside the rolled-back fixture.
    db_session.execute(text("ALTER TABLE programmes DROP CONSTRAINT ck_programmes_category"))
    categories = ", ".join(
        f"'{category}'" for category in PROGRAMME_CATEGORY_LABELS if category != "government_exam"
    )
    db_session.execute(
        text(
            "ALTER TABLE programmes ADD CONSTRAINT ck_programmes_category "
            f"CHECK (category IN ({categories})) NOT VALID"
        )
    )
    return db_session


def test_real_json_metadata_parity_without_database():
    assert metadata_gaps() == ([], [])


@pytest.mark.parametrize(
    "today,end",
    [(date(2026, 11, 17), date(2027, 11, 16)), (date(2028, 2, 29), date(2029, 2, 27))],
)
def test_default_window_matches_page_next12(today, end):
    assert calendar_public.default_calendar_window(today) == (today, end)


def bucket_sum(result):
    return (
        result.published_dated
        + result.published_rolling
        + result.outside_window
        + result.closed
        + result.retired
        + len(result.skipped)
        + len(result.pending_import)
        + len(result.unexplained)
    )


def test_exactly_one_bucket_aliases_occurrences_and_query_budget(seeded):
    statements = []

    def capture(*args):
        statements.append(args[2])

    connection = seeded.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        result = reconcile_calendar(seeded, today=TODAY)
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert len(statements) == 3
    assert result.source_rows == result.metadata_programmes == bucket_sum(result) == 12
    assert (result.published_dated, result.published_rolling) == (3, 1)
    assert result.published_total == 4
    assert (result.outside_window, result.closed, result.retired) == (2, 1, 2)
    assert result.active_programmes == 10
    assert result.registry_only_active == 1
    assert result.skipped[0].slug == "cal-skipped"
    assert result.skipped[0].reason == "ck_programmes_category rejects category government_exam"
    assert [row.slug for row in result.pending_import] == ["cal-pending"]
    assert [(row.row_id, row.slug) for row in result.unexplained] == [
        ("ROW-unexplained", "cal-unexplained")
    ]
    assert result.to_dict()["window"] == {
        "from": "2026-11-17",
        "to": "2027-11-16",
        "as_of": "2026-11-17",
    }
    json.dumps(result.to_dict())
    with pytest.raises(FrozenInstanceError):
        result.source_rows = 0


def test_import_retirement_and_skips_reconcile_without_changing_report_keys(seeded):
    result = importer.import_calendar(seeded)
    assert result == {"imported": 11, "skipped": 1}
    coverage = reconcile_calendar(seeded, today=TODAY)
    assert coverage.pending_import == coverage.unexplained == []
    assert bucket_sum(coverage) == coverage.source_rows
    assert len(coverage.skipped) == 1
    retired = seeded.scalar(select(Programme).where(Programme.slug == "cal-retired"))
    assert retired.is_active is False


def test_metadata_gaps_are_reported_and_missing_metadata_is_unexplained(seeded, monkeypatch):
    monkeypatch.delitem(source.CALENDAR_META, "cal-pending")
    monkeypatch.setitem(
        source.CALENDAR_META,
        "orphan",
        {
            "row_id": "ABSENT",
            "name": "orphan",
            "organiser": "Other",
            "cycle_year": 2027,
        },
    )
    result = reconcile_calendar(seeded, today=TODAY)
    assert result.rows_without_metadata_ids == ["ROW-pending"]
    assert result.metadata_without_row_ids == ["ABSENT"]
    assert result.rows_without_metadata == result.metadata_without_row == 1
    assert ("ROW-pending", "") in [(row.row_id, row.slug) for row in result.unexplained]
    assert bucket_sum(result) == result.source_rows


def test_coverage_api_matches_unique_source_programmes_and_public_cache(seeded, monkeypatch):
    retired = seeded.scalar(select(Programme).where(Programme.slug == "cal-retired"))
    retired.is_active = False
    seeded.flush()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 12, tzinfo=source.IST)

    monkeypatch.setattr(calendar_api, "datetime", FrozenDateTime)
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    cache, ttls = {}, []

    async def get_cached(redis, key, **kwargs):
        return cache.get(key)

    async def set_cached(redis, key, value, ttl, **kwargs):
        cache[key] = value
        ttls.append(ttl)

    monkeypatch.setattr(middleware, "cache_get", get_cached)
    monkeypatch.setattr(middleware, "cache_set", set_cached)
    app = FastAPI()
    app.include_router(calendar_api.router)
    app.dependency_overrides[get_db] = lambda: seeded
    app.add_middleware(middleware.ReadCacheMiddleware)
    with TestClient(app) as client:
        first = client.get("/calendar/coverage")
        assert first.status_code == 200
        coverage = first.json()
        assert coverage == reconcile_calendar(seeded, today=TODAY).to_dict()
        assert set(coverage["unexplained"][0]) == {"row_id", "slug"}
        assert set(coverage["skipped"][0]) == {"row_id", "slug", "reason"}
        assert first.headers["x-cache"] == "MISS"
        app.dependency_overrides[get_db] = lambda: pytest.fail("cache hit opened DB")
        assert client.get("/calendar/coverage").headers["x-cache"] == "HIT"
        app.dependency_overrides[get_db] = lambda: seeded
        public = client.get(
            "/calendar", params={"from": coverage["window"]["from"], "to": coverage["window"]["to"]}
        )
        assert first.headers["cache-control"] == public.headers["cache-control"]
        for field, collection in (("published_dated", "items"), ("published_rolling", "rolling")):
            ids = {item["metadata"]["row_id"] for item in public.json()[collection]}
            assert coverage[field] == len(ids - {None})
    assert ttls == [get_settings().read_cache_ttl_seconds] * 2
    assert not middleware._is_cacheable("/calendar/watches")


def test_coverage_and_calendar_share_rate_limit_before_db(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_ip_opportunity_per_minute", 1)
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    app = FastAPI()
    app.include_router(calendar_api.router)

    class EmptyDB:
        def scalars(self, statement):
            return []

    app.dependency_overrides[get_db] = lambda: EmptyDB()
    app.add_middleware(middleware.ReadCacheMiddleware)
    app.add_middleware(middleware.RateLimitMiddleware)
    with TestClient(app) as client:
        assert client.get("/calendar?from=2027-01-01&to=2027-02-01").status_code == 200
        app.dependency_overrides[get_db] = lambda: pytest.fail("limited request opened DB")
        response = client.get("/calendar/coverage")
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0


@pytest.mark.parametrize("failure", ["pending_import", "unexplained", None])
def test_refresh_commits_before_gate_and_fails_nonzero(seeded, monkeypatch, caplog, failure):
    # A dedicated Session joins an outer throwaway transaction via SAVEPOINT.
    # main() can genuinely commit; a second session observes that commit, and
    # the outer fixture rollback still cleans every test row.
    connection = seeded.connection()
    work = Session(bind=connection, join_transaction_mode="create_savepoint")

    def run_import(session, fetcher):
        session.add(
            Programme(
                slug="committed-refresh",
                name="Committed import",
                organiser="Other",
                category="research_internship",
                url="https://example.org",
                tags=[],
            )
        )
        return {"imported": 1, "skipped": 0}

    def reconcile_after_commit(session, *, today):
        with Session(bind=connection, join_transaction_mode="create_savepoint") as observer:
            assert (
                observer.scalar(select(Programme).where(Programme.slug == "committed-refresh"))
                is not None
            )
        assert not session.in_transaction()
        result = reconcile_calendar(session, today=TODAY)
        from dataclasses import replace

        return replace(
            result,
            pending_import=result.pending_import if failure == "pending_import" else [],
            unexplained=result.unexplained if failure == "unexplained" else [],
        )

    monkeypatch.setattr(refresh, "Session", lambda engine: work)
    monkeypatch.setattr(refresh, "make_engine", lambda: None)
    monkeypatch.setattr(refresh, "refresh_calendar", run_import)
    monkeypatch.setattr(refresh, "reconcile_calendar", reconcile_after_commit)
    with caplog.at_level("INFO"):
        if failure:
            with pytest.raises(SystemExit) as exc:
                refresh.main()
            assert exc.value.code == 1
        else:
            refresh.main()
    lines = [
        record.message
        for record in caplog.records
        if record.message.startswith("Calendar reconciliation ")
    ]
    assert len(lines) == 1
    body = json.loads(lines[0].removeprefix("Calendar reconciliation "))
    assert bool(body[failure]) if failure else not body["unexplained"]
    assert (
        seeded.scalar(select(Programme.id).where(Programme.slug == "committed-refresh")) is not None
    )
