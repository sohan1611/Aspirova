"""Generic digests reuse the feed's soft country preference (2026-11-17 ruling)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import digest
from api.deps import get_db
from api.filters import preferred_country_rank
from api.main import app
from core import models
from core.config import get_settings
from pipeline import notifications as worker

NOW = datetime(2033, 4, 1, 12, tzinfo=timezone.utc)
SINCE = NOW - timedelta(hours=24)


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


def _company(db, prestige_rank=None):
    suffix = uuid.uuid4().hex
    company = models.Company(
        slug=f"digest-country-{suffix}",
        name=f"Digest country {suffix}",
        prestige_rank=prestige_rank,
    )
    db.add(company)
    db.flush()
    return company


def _role(db, company, country, *, remote=False, category="internship", minutes_ago=1):
    row = models.Opportunity(
        slug=f"digest-country-{uuid.uuid4().hex}",
        company_id=company.id,
        title="Software Engineering Intern" if category == "internship" else "Software Engineer",
        title_normalized=(
            "software engineering intern" if category == "internship" else "software engineer"
        ),
        category=category,
        country=country,
        is_remote=remote,
        apply_url="https://example.com/apply",
        status="active",
        first_seen_at=NOW - timedelta(minutes=minutes_ago),
        last_seen_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize(
    "country,remote,expected",
    [
        ("IN", False, 0),
        ("IN", True, 0),
        (None, True, 1),
        ("", True, 1),
        ("  ", True, 1),
        ("BR", True, 2),
        ("BR", False, 2),
        (None, False, 2),
        ("", False, 2),
        (None, None, 2),
    ],
)
def test_shared_preferred_country_rank_three_tiers(db_session, country, remote, expected):
    row = _role(db_session, _company(db_session), country, remote=remote)

    rank = db_session.scalar(
        select(preferred_country_rank("in")).where(models.Opportunity.id == row.id)
    )
    assert rank == expected


@pytest.mark.parametrize("prestige_ranks", [(1, 100), (None, None)])
def test_india_precedes_brazil_in_reserve_and_fill(db_session, prestige_ranks):
    brazil = _role(db_session, _company(db_session, prestige_ranks[0]), "BR")
    # Country takes precedence over both prestige and internship/job rank.
    india = _role(
        db_session,
        _company(db_session, prestige_ranks[1]),
        "IN",
        category="job",
        minutes_ago=30,
    )

    picks = worker._generic_recent_opportunities(db_session, SINCE, 1, NOW)

    assert [row.id for row in picks] == [india.id]
    assert brazil.id not in {row.id for row in picks}


def test_company_representative_prefers_india_over_newer_brazil_internship(db_session):
    company = _company(db_session, 1)
    _role(db_session, company, "BR")
    india = _role(db_session, company, "IN", category="job", minutes_ago=30)

    picks = worker._generic_recent_opportunities(db_session, SINCE, 5, NOW)

    assert [row.id for row in picks] == [india.id]


@pytest.mark.parametrize("limit", [2, 6])
def test_digest_country_tiers_apply_to_selection_and_final_order(db_session, limit):
    rows = {}
    for name, country, remote, prestige, category in [
        ("india", "IN", False, 100, "job"),
        ("global-null", None, True, 50, "internship"),
        ("global-empty", "", True, 40, "internship"),
        ("global-space", "  ", True, 30, "internship"),
        ("brazil-remote", "BR", True, 1, "internship"),
        ("brazil-office", "BR", False, 2, "internship"),
    ]:
        rows[name] = _role(
            db_session,
            _company(db_session, prestige),
            country,
            remote=remote,
            category=category,
        )

    picks = worker._generic_recent_opportunities(db_session, SINCE, limit, NOW)

    expected = [
        "india",
        "global-space",
        "global-empty",
        "global-null",
        "brazil-remote",
        "brazil-office",
    ]
    assert [row.id for row in picks] == [rows[name].id for name in expected[:limit]]


def test_elsewhere_still_fills_digest_and_keeps_ranked_company_reserve(db_session):
    rows = []
    for index in range(6):
        rows.append(
            _role(
                db_session,
                _company(db_session, index + 1 if index < 2 else None),
                "BR" if index % 2 else "US",
                category="job" if index < 2 else "internship",
                minutes_ago=index + 1,
            )
        )

    picks = worker._generic_recent_opportunities(db_session, SINCE, 5, NOW)

    # Same five picks and student/prestige ordering as before the country preference.
    assert [row.id for row in picks] == [rows[index].id for index in (2, 3, 4, 0, 1)]
    assert len(picks) == 5
    assert len({row.company_id for row in picks}) == 5


def test_reserve_skips_famous_role_abroad_while_local_roles_remain(db_session):
    # One ranked company has an India role; a higher-ranked company only has a
    # role in Brazil. Ordinary India roles are plentiful, so the Brazil role must
    # not take the second reserve slot ahead of them.
    ranked_india = _role(db_session, _company(db_session, 5), "IN", category="job")
    brazil = _role(db_session, _company(db_session, 1), "BR")
    local = [
        _role(db_session, _company(db_session), "IN", minutes_ago=index + 2) for index in range(4)
    ]

    picks = worker._generic_recent_opportunities(db_session, SINCE, 5, NOW)

    assert brazil.id not in {row.id for row in picks}
    assert {row.id for row in picks} == {ranked_india.id, *(row.id for row in local)}
    assert all(row.country == "IN" for row in picks)


def test_reserve_still_uses_role_abroad_when_no_local_role_exists(db_session):
    brazil = _role(db_session, _company(db_session, 1), "BR")
    us = _role(db_session, _company(db_session, 2), "US", minutes_ago=2)

    picks = worker._generic_recent_opportunities(db_session, SINCE, 5, NOW)

    assert [row.id for row in picks] == [brazil.id, us.id]


@pytest.mark.parametrize(
    "profile,expected_country",
    [
        (None, "IN"),
        ({}, "IN"),
        ({"interests": ["data"]}, "IN"),
        ({"country": None}, "IN"),
        ({"country": "BR"}, "BR"),
        ({"country": "US"}, "US"),
    ],
)
def test_reader_country_overrides_india_default(db_session, monkeypatch, profile, expected_country):
    rows = {
        country: _role(db_session, _company(db_session, prestige), country)
        for country, prestige in [("BR", 1), ("US", 2), ("IN", 100)]
    }
    user = models.User(
        email=f"digest-country-{uuid.uuid4().hex}@example.com",
        field_profile=profile,
        notification_prefs={"hackathon_digest": False},
    )
    db_session.add(user)
    db_session.flush()
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"digest-country-test-key")

    draft = worker.compose_daily_digest(
        db_session, user, NOW, worker._HackathonPicks(db_session, NOW)
    )

    assert worker.DIGEST_GENERIC_COUNTRY == "IN"
    assert draft.opportunities[0].id == rows[expected_country].id
    assert {row.id for row in draft.opportunities} == {row.id for row in rows.values()}


def test_public_digest_sample_returns_india_first(db_session, monkeypatch):
    brazil = _role(db_session, _company(db_session, 1), "BR")
    india = _role(db_session, _company(db_session, 100), "IN", category="job")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(digest, "datetime", FrozenDateTime)
    monkeypatch.setattr(worker, "_hackathon_digest_opportunities", lambda *args: [])
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "memory")
    monkeypatch.setattr(get_settings(), "read_cache_l2_enabled", False)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        response = TestClient(app).get("/digest/sample")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["items"]] == [india.slug, brazil.slug]
