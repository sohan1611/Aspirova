"""Postgres integration checks. Use a disposable, migrated test database only."""

import importlib.util
import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.filters import (
    location_scope_filters,
    regions_for_country,
    saved_search_base_filters,
    visa_filters,
)
from api.main import app
from api.schemas import SavedSearchParams
from api.saved_searches import _validated_params
from core import models
from core.eligibility_facts import extract_eligibility_facts
from scripts import backfill_eligibility_facts as backfill


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(connection)
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def listings(db_session):
    token = uuid.uuid4().hex
    company = models.Company(slug="eligibility-" + token, name="Eligibility " + token)
    descriptions = [
        None,
        "Work on useful projects.",
        "2026 batch; Currently pursuing a bachelor’s degree",
        "2025 batch; Currently pursuing a master’s degree",
        "2026 batch",
    ]
    rows = [
        models.Opportunity(
            slug=f"eligibility-{token}-{index}",
            title="Developer Intern",
            company=company,
            description_raw=description,
            category="internship",
            apply_url="https://example.com/apply",
            primary_source="greenhouse",
            status="active",
            posted_at=datetime.now(UTC) - timedelta(hours=index),
            last_seen_at=datetime.now(UTC),
        )
        for index, description in enumerate(descriptions)
    ]
    db_session.add_all(rows)
    db_session.flush()
    # Legacy rows are NULL in storage; bypass the mapper event deliberately.
    db_session.execute(
        update(models.Opportunity)
        .where(models.Opportunity.id == rows[0].id)
        .values(eligibility_facts=None)
    )
    db_session.flush()
    return company, rows


@pytest.mark.parametrize("path", ["/feed", "/search"])
@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"grad_year": 2026}, [0, 1, 2, 4]),
        ({"stage": "undergraduate"}, [0, 1, 2, 4]),
        ({"stage": "undergraduate,postgraduate"}, [0, 1, 2, 3, 4]),
        ({"grad_year": 2026, "eligibility_stated": True}, [2, 4]),
        ({"stage": "undergraduate", "eligibility_stated": True}, [2]),
        ({"grad_year": 2026, "stage": "undergraduate", "eligibility_stated": True}, [2]),
        ({"eligibility_stated": True}, [0, 1, 2, 3, 4]),
    ],
)
def test_filter_unknown_and_stated_semantics(client, listings, path, filters, expected):
    company, rows = listings
    params = {"company": company.slug, "limit": 100, "sort": "recent", **filters}
    if path == "/search":
        params["q"] = "Developer"
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["slug"] for item in items} == {rows[index].slug for index in expected}
    assert all("eligibility" in item and "description_raw" not in item for item in items)
    legacy = next((item for item in items if item["slug"] == rows[0].slug), None)
    if legacy:
        assert legacy["eligibility"] is None
    detail = client.get("/opportunity/" + rows[2].slug)
    assert detail.status_code == 200
    assert detail.json()["eligibility"]["grad_years"]["value"] == [2026]


@pytest.mark.parametrize("path", ["/feed", "/search"])
@pytest.mark.parametrize("sort", ["student", "recent", "deadline", "pay", "prize"])
def test_no_reordering_of_surviving_rows(client, listings, path, sort):
    company, rows = listings
    params = {"company": company.slug, "limit": 100, "sort": sort}
    if path == "/search":
        params["q"] = "Developer"
    baseline = client.get(path, params=params).json()["items"]
    filtered = client.get(path, params={**params, "grad_year": 2026}).json()["items"]
    assert [item["slug"] for item in filtered] == [
        item["slug"] for item in baseline if item["slug"] != rows[3].slug
    ]


def test_saved_search_filters_preserve_unknown(db_session, listings):
    _, rows = listings
    params = _validated_params(SavedSearchParams(grad_year=2026, stage=["undergraduate"]))
    assert params == {"grad_year": 2026, "stage": ["undergraduate"]}

    def selected(values):
        return set(
            db_session.scalars(
                select(models.Opportunity.id).where(
                    models.Opportunity.id.in_([row.id for row in rows]),
                    *saved_search_base_filters(values),
                )
            )
        )

    assert selected(params) == {rows[index].id for index in [0, 1, 2, 4]}
    assert selected({**params, "eligibility_stated": True}) == {rows[2].id}


@pytest.mark.parametrize("path", ["/feed", "/search"])
def test_cache_keys_and_validation(client, listings, path):
    company, _ = listings
    base = {"company": company.slug}
    if path == "/search":
        base["q"] = "Developer"
    baseline = client.get(path, params=base)
    assert baseline.headers["x-cache"] == "MISS"
    for params in (
        {"grad_year": 2026},
        {"grad_year": 2025},
        {"stage": "undergraduate"},
        {"stage": "postgraduate"},
        {"grad_year": 2026, "eligibility_stated": True},
    ):
        first = client.get(path, params={**base, **params})
        assert first.status_code == 200
        assert first.headers["x-cache"] == "MISS"
        assert client.get(path, params={**base, **params}).headers["x-cache"] == "HIT"
    for invalid in ({"grad_year": 2014}, {"grad_year": 2036}, {"stage": "astronaut"}):
        assert client.get(path, params={**base, **invalid}).status_code == 422


def test_mapper_content_changes_and_fast_path(db_session, listings, monkeypatch):
    import core.eligibility_facts as parser

    _, rows = listings
    row = rows[1]
    real = parser.extract_eligibility_facts
    spy = Mock(wraps=real)
    monkeypatch.setattr(parser, "extract_eligibility_facts", spy)
    for attribute, value, key in (
        ("title", "2027 batch", "grad_years"),
        ("description_raw", "PhD student", "stages"),
        ("meta", {"eligibility": ["US citizens only"]}, "citizenship"),
    ):
        setattr(row, attribute, value)
        db_session.flush()
        assert key in row.eligibility_facts
    assert spy.call_count == 3
    row.last_seen_at = datetime.now(UTC) + timedelta(days=1)
    db_session.flush()
    assert spy.call_count == 3
    db_session.execute(
        update(models.Opportunity)
        .where(models.Opportunity.id == row.id)
        .values(meta={"liveness_checked_at": "2026-11-22"})
    )
    assert spy.call_count == 3


@pytest.fixture
def eligibility_schema(engine, monkeypatch):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/fa5b8e3c7d21_add_eligibility_facts.py"
    )
    spec = importlib.util.spec_from_file_location("eligibility_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = "eligibility_test_" + uuid.uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
            connection.exec_driver_sql(
                "CREATE TABLE opportunities (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, title text NOT NULL, description_raw text, meta jsonb, status text DEFAULT 'active', location text, is_remote boolean)"
            )
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            yield connection, migration
        finally:
            transaction.rollback()


def test_migration_contract_no_rewrite_and_downgrade(eligibility_schema):
    connection, migration = eligibility_schema
    connection.exec_driver_sql("INSERT INTO opportunities(title) VALUES ('2026 batch')")
    filenode = connection.scalar(text("SELECT pg_relation_filenode('opportunities')"))
    migration.upgrade()
    column = next(
        c
        for c in inspect(connection).get_columns("opportunities")
        if c["name"] == "eligibility_facts"
    )
    assert column["nullable"] and column["default"] is None and isinstance(column["type"], JSONB)
    assert connection.scalar(text("SELECT pg_relation_filenode('opportunities')")) == filenode
    assert connection.scalar(text("SELECT eligibility_facts IS NULL FROM opportunities"))
    orm_column = models.Opportunity.__table__.c.eligibility_facts
    assert orm_column.nullable and orm_column.server_default is None
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    assert ScriptDirectory.from_config(config).get_heads() == [migration.revision]
    migration.downgrade()
    assert "eligibility_facts" not in {
        c["name"] for c in inspect(connection).get_columns("opportunities")
    }


@pytest.mark.parametrize("batch", [1, 2, 500])
def test_backfill_batches_dry_run_versions_and_scope(
    eligibility_schema, batch, monkeypatch, capsys
):
    connection, migration = eligibility_schema
    migration.upgrade()
    connection.exec_driver_sql(
        "INSERT INTO opportunities(title, status) VALUES ('2026 batch', 'active'), ('PhD student', 'active'), ('Role', 'active'), ('Role', 'expired')"
    )
    connection.exec_driver_sql(
        "UPDATE opportunities SET eligibility_facts = '{\"v\":2}'::jsonb WHERE id=2"
    )
    # Row 3 is already parsed by the current parser version, so it is not due.
    connection.exec_driver_sql(
        "UPDATE opportunities SET eligibility_facts = jsonb_build_object('v', %(v)s) WHERE id=3",
        {"v": backfill.ELIGIBILITY_FACTS_VERSION},
    )
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        assert backfill.backfill_eligibility_facts(connection, batch=batch, dry_run=True) == {
            "updated": 0,
            "remaining": 2,
        }
        assert not any(s.startswith("UPDATE ") for s in statements)
        assert backfill.backfill_eligibility_facts(connection, batch=batch) == {
            "updated": 2,
            "remaining": 0,
        }
        updates = [s for s in statements if s.startswith("UPDATE ")]
        assert len(updates) == math.ceil(2 / batch)
        assert all("FROM (VALUES" in s for s in updates)
        assert "SET LOCAL lock_timeout = '3s'" in statements
        assert "SET LOCAL statement_timeout = '30s'" in statements
        assert backfill.backfill_eligibility_facts(connection) == {"updated": 0, "remaining": 0}
        assert connection.scalar(
            text("SELECT eligibility_facts IS NULL FROM opportunities WHERE id=4")
        )
        assert backfill.backfill_eligibility_facts(connection, include_inactive=True) == {
            "updated": 1,
            "remaining": 0,
        }
        # A future parser version must pick up already-parsed rows too.
        future = backfill.ELIGIBILITY_FACTS_VERSION + 1
        monkeypatch.setattr(backfill, "ELIGIBILITY_FACTS_VERSION", future)
        real = extract_eligibility_facts
        monkeypatch.setattr(
            backfill,
            "extract_eligibility_facts",
            lambda *args, **kwargs: {**real(*args, **kwargs), "v": future},
        )
        assert backfill.backfill_eligibility_facts(connection, batch=batch) == {
            "updated": 3,
            "remaining": 0,
        }
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert re.fullmatch(r"(?:rows_updated=\d+ remaining=\d+\n){5}", capsys.readouterr().out)


@pytest.mark.parametrize(
    "country,remote,expected",
    [
        (
            None,
            True,
            {
                "domestic": {"including", "worldwide", "region", "unknown", "null"},
                "remote_abroad": {"including", "worldwide", "region", "unknown", "null"},
                "abroad": {"other", "unknown", "null"},
            },
        ),
        (
            "US",
            True,
            {
                "domestic": set(),
                "remote_abroad": {"including", "worldwide", "region", "unknown", "null"},
                "abroad": {"other", "unknown", "null"},
            },
        ),
        (
            "IN",
            True,
            {
                "domestic": {"other", "including", "worldwide", "region", "unknown", "null"},
                "remote_abroad": {"other", "including", "worldwide", "region", "unknown", "null"},
                "abroad": set(),
            },
        ),
        (None, False, {"domestic": set(), "remote_abroad": set(), "abroad": set()}),
        (
            "US",
            False,
            {
                "domestic": set(),
                "remote_abroad": set(),
                "abroad": {"other", "including", "worldwide", "region", "unknown", "null"},
            },
        ),
        (
            "IN",
            False,
            {
                "domestic": {"other", "including", "worldwide", "region", "unknown", "null"},
                "remote_abroad": {"other", "including", "worldwide", "region", "unknown", "null"},
                "abroad": set(),
            },
        ),
    ],
)
def test_remote_scope_truth_table(db_session, country, remote, expected):
    token = uuid.uuid4().hex
    definitions = {
        "other": ["US"],
        "including": ["IN", "PH"],
        "worldwide": ["WORLDWIDE"],
        "region": ["ASIA"],
        "unknown": None,
        "null": None,
    }
    ids = {}
    for name, regions in definitions.items():
        row = models.Opportunity(
            slug=f"disc06-{token}-{name}",
            title="Developer",
            apply_url="https://example.com/apply",
            country=country,
            is_remote=remote,
        )
        db_session.add(row)
        db_session.flush()
        facts = {"v": 3}
        if regions is not None:
            facts["remote_regions"] = {
                "value": regions,
                "evidence": "Source restriction",
                "source": "description",
            }
        db_session.execute(
            update(models.Opportunity)
            .where(models.Opportunity.id == row.id)
            .values(eligibility_facts=None if name == "null" else facts)
        )
        ids[row.id] = name
    for mode in ("domestic", "remote_abroad", "abroad"):
        clauses = location_scope_filters(
            "domestic" if mode == "remote_abroad" else mode, "in", mode == "remote_abroad"
        )
        selected = db_session.scalars(
            select(models.Opportunity.id).where(models.Opportunity.id.in_(ids), *clauses)
        )
        assert {ids[identifier] for identifier in selected} == expected[mode]


@pytest.mark.parametrize(
    "country,tokens",
    [
        ("IN", {"IN", "WORLDWIDE", "ASIA", "APAC"}),
        ("GB", {"GB", "WORLDWIDE", "EUROPE", "EMEA"}),
        ("DE", {"DE", "WORLDWIDE", "EUROPE", "EMEA"}),
        ("FR", {"FR", "WORLDWIDE", "EUROPE", "EMEA"}),
        ("US", {"US", "WORLDWIDE", "NORTH_AMERICA"}),
        ("CA", {"CA", "WORLDWIDE", "NORTH_AMERICA"}),
        ("MX", {"MX", "WORLDWIDE", "NORTH_AMERICA", "LATAM"}),
        ("BR", {"BR", "WORLDWIDE", "LATAM"}),
        ("AR", {"AR", "WORLDWIDE", "LATAM"}),
        ("AE", {"AE", "WORLDWIDE", "ASIA", "MIDDLE_EAST", "EMEA"}),
        ("SA", {"SA", "WORLDWIDE", "ASIA", "MIDDLE_EAST", "EMEA"}),
        ("ZA", {"ZA", "WORLDWIDE", "AFRICA", "EMEA"}),
        ("NG", {"NG", "WORLDWIDE", "AFRICA", "EMEA"}),
        ("KE", {"KE", "WORLDWIDE", "AFRICA", "EMEA"}),
        ("SG", {"SG", "WORLDWIDE", "ASIA", "APAC"}),
        ("JP", {"JP", "WORLDWIDE", "ASIA", "APAC"}),
        ("AU", {"AU", "WORLDWIDE", "APAC"}),
        ("AQ", {"AQ", "WORLDWIDE"}),
    ],
)
def test_explicit_country_region_coverage(country, tokens):
    assert regions_for_country(country.lower()) == sorted(tokens)


@pytest.fixture
def visa_listings(db_session):
    token = uuid.uuid4().hex
    company = models.Company(slug="disc06-visa-" + token, name="Visa " + token)
    descriptions = [
        None,
        "Work on projects",
        "No visa sponsorship",
        "Visa sponsorship available",
        "Must be authorized to work in India",
        "Must be authorized to work in the US",
        "Must have work authorization",
        "Must have work authorization in India and Canada",
    ]
    rows = [
        models.Opportunity(
            slug=f"disc06-visa-{token}-{i}",
            title="Developer Intern",
            company=company,
            category="internship",
            description_raw=description,
            status="active",
            primary_source="greenhouse",
            apply_url="https://example.com/apply",
            last_seen_at=datetime.now(UTC),
        )
        for i, description in enumerate(descriptions)
    ]
    db_session.add_all(rows)
    db_session.flush()
    db_session.execute(
        update(models.Opportunity)
        .where(models.Opportunity.id == rows[0].id)
        .values(eligibility_facts=None)
    )
    return company, rows


@pytest.mark.parametrize("path", ["/feed", "/search"])
@pytest.mark.parametrize(
    "country,expected", [("IN", [0, 1, 3, 4, 6]), (None, [0, 1, 3, 4, 5, 6, 7])]
)
def test_visa_opt_in_endpoints_cache_and_saved_search(
    client, db_session, visa_listings, path, country, expected
):
    company, rows = visa_listings
    base = {"company": company.slug, "limit": 100, "sort": "recent"}
    if path == "/search":
        base["q"] = "Developer"
    if country:
        base["country"] = country
    before = client.get(path, params=base)
    assert before.status_code == 200
    assert len(before.json()["items"]) == len(rows)
    response = client.get(path, params={**base, "visa": "needs"})
    assert response.status_code == 200, response.text
    assert response.headers["x-cache"] == "MISS"
    assert client.get(path, params={**base, "visa": "needs"}).headers["x-cache"] == "HIT"
    filtered = [item["slug"] for item in response.json()["items"]]
    assert set(filtered) == {rows[i].slug for i in expected}
    assert filtered == [
        item["slug"] for item in before.json()["items"] if item["slug"] in set(filtered)
    ]
    params = _validated_params(SavedSearchParams(visa="needs", country=country))
    selected = set(
        db_session.scalars(
            select(models.Opportunity.id).where(
                models.Opportunity.id.in_([row.id for row in rows]),
                *saved_search_base_filters(params),
            )
        )
    )
    assert selected == {rows[i].id for i in expected}
    assert visa_filters() == []
    assert client.get(path, params={**base, "visa": "invalid"}).status_code == 422


def test_location_and_remote_mapper_changes(db_session, listings):
    _, rows = listings
    row = rows[1]
    row.location = "India, Philippines"
    row.is_remote = False
    db_session.flush()
    assert "remote_regions" not in row.eligibility_facts
    row.is_remote = True
    db_session.flush()
    assert row.eligibility_facts["remote_regions"]["value"] == ["IN", "PH"]
    assert row.eligibility_facts["remote_regions"]["source"] == "location"
    assert "remote_mode" not in row.eligibility_facts
    row.location = "United States"
    db_session.flush()
    assert row.eligibility_facts["remote_regions"]["value"] == ["US"]
    row.is_remote = False
    db_session.flush()
    assert "remote_regions" not in row.eligibility_facts


def test_backfill_v2_reads_remote_location(eligibility_schema):
    connection, migration = eligibility_schema
    migration.upgrade()
    connection.exec_driver_sql(
        "INSERT INTO opportunities(title, location, is_remote, eligibility_facts) VALUES ('Role', 'India, Philippines', true, '{\"v\":2}'::jsonb)"
    )
    assert backfill.backfill_eligibility_facts(connection) == {"updated": 1, "remaining": 0}
    facts = connection.scalar(text("SELECT eligibility_facts FROM opportunities"))
    assert facts["v"] == 3
    assert facts["remote_regions"]["value"] == ["IN", "PH"]
    assert "remote_mode" not in facts


@pytest.mark.parametrize("path", ["/feed", "/search"])
def test_declared_visa_cache_keys(path):
    from core.cache import build_cache_key

    route = next(route for route in middleware._iter_api_routes(app.routes) if route.path == path)
    allowed = middleware._declared_query_param_names(route)
    assert "visa" in allowed
    assert build_cache_key(path, [], allowed) != build_cache_key(path, [("visa", "needs")], allowed)
