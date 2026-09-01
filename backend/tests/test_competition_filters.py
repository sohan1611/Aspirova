import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.filters import normalize_competition_mode
from api.main import app
from core import models


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


@pytest.fixture
def client(db_session: Session, monkeypatch):
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def competition_rows(db_session: Session):
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    location_token = f"CompetitionFilterville-{suffix}"

    iit = models.Company(
        slug=f"competition-filter-iit-{suffix}",
        name=f"Indian Institute of Technology (IIT), Bhubaneswar {suffix}",
    )
    company = models.Company(
        slug=f"competition-filter-company-{suffix}",
        name=f"Pixel Labs Pvt Ltd {suffix}",
    )
    university = models.Company(
        slug=f"competition-filter-university-{suffix}",
        name=f"State University {suffix}",
    )
    other = models.Company(
        slug=f"competition-filter-other-{suffix}",
        name=f"Neighborhood Organiser {suffix}",
    )
    role_company = models.Company(
        slug=f"competition-filter-role-company-{suffix}",
        name=f"Role Facet Employer {suffix}",
    )

    online_iit = models.Opportunity(
        slug=f"competition-filter-online-iit-{suffix}",
        title="Online coding challenge",
        company=iit,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/competition-filter/online-iit/{suffix}",
        deadline=now + timedelta(days=2),
        posted_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now,
        status="active",
        meta={
            "subtype": "online_coding_challenge",
            "is_paid": False,
            "mode": "Online",
            "prizes": [{"cash": 150000, "rank": 1, "currency": "fa-rupee"}],
        },
    )
    offline_company = models.Opportunity(
        slug=f"competition-filter-offline-company-{suffix}",
        title="Paid case competition",
        company=company,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/competition-filter/offline-company/{suffix}",
        deadline=now + timedelta(days=10),
        posted_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(minutes=1),
        status="active",
        meta={
            "subtype": "case_competition",
            "is_paid": True,
            "mode": "offline",
            "prizes": [{"cash": 900000, "rank": 1, "currency": "fa-dollar"}],
        },
    )
    hybrid_university = models.Opportunity(
        slug=f"competition-filter-hybrid-university-{suffix}",
        title="Hybrid innovation challenge",
        company=university,
        category="hackathon",
        location=location_token,
        apply_url=f"https://example.com/competition-filter/hybrid-university/{suffix}",
        deadline=now + timedelta(days=20),
        posted_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(minutes=2),
        status="active",
        meta={
            "subtype": "innovation_challenge",
            "is_paid": False,
            "mode": "hybrid",
        },
    )
    unknown_mode = models.Opportunity(
        slug=f"competition-filter-unknown-mode-{suffix}",
        title="Venue leaked as mode",
        company=other,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/competition-filter/unknown-mode/{suffix}",
        deadline=now + timedelta(days=40),
        posted_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(minutes=3),
        status="active",
        meta={
            "subtype": "hiring_challenge",
            "is_paid": False,
            "mode": "Jaipur",
        },
    )
    no_deadline = models.Opportunity(
        slug=f"competition-filter-no-deadline-{suffix}",
        title="Undated general competition",
        company=other,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/competition-filter/no-deadline/{suffix}",
        posted_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(minutes=4),
        status="active",
        meta={
            "subtype": "general_competition",
            "is_paid": False,
            "mode": "online",
        },
    )
    role = models.Opportunity(
        slug=f"competition-filter-role-{suffix}",
        title="Backend role",
        company=role_company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/competition-filter/role/{suffix}",
        posted_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now,
        status="active",
    )

    db_session.add_all(
        [
            iit,
            company,
            university,
            other,
            role_company,
            online_iit,
            offline_company,
            hybrid_university,
            unknown_mode,
            no_deadline,
            role,
        ]
    )
    db_session.flush()

    return {
        "location": location_token,
        "iit": iit,
        "company": company,
        "university": university,
        "role_company": role_company,
        "online_iit": online_iit,
        "offline_company": offline_company,
        "hybrid_university": hybrid_university,
        "unknown_mode": unknown_mode,
        "no_deadline": no_deadline,
        "role": role,
    }


def _slugs(body: dict) -> set[str]:
    return {item["slug"] for item in body["items"]}


def _facet_by_value(options: list[dict], value: str) -> dict | None:
    return next((option for option in options if option["value"] == value), None)


def _facet_by_label(options: list[dict], label: str) -> dict | None:
    return next((option for option in options if option["label"] == label), None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("online", "online"),
        ("offline", "offline"),
        ("Online", "online"),
        ("hybrid", "hybrid"),
        ("Jaipur", "unknown"),
        ("University of Sydney", "unknown"),
        ("KIT main building", "unknown"),
        ("VITM Indore", "unknown"),
        ("Pitkin, CO, USA", "unknown"),
    ],
)
def test_mode_normalisation_collapses_real_dirty_values(raw: str, expected: str) -> None:
    """Mode leaked venue names in production, so only three buckets are UI-safe."""
    assert normalize_competition_mode(raw) == expected


def test_absent_competition_params_leave_the_competition_feed_unchanged(
    client: TestClient, competition_rows
) -> None:
    """Existing callers with no advanced params should still see every scoped row."""
    body = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "limit": 10,
        },
    ).json()

    assert body["total"] == 5
    assert _slugs(body) == {
        competition_rows["online_iit"].slug,
        competition_rows["offline_company"].slug,
        competition_rows["hybrid_university"].slug,
        competition_rows["unknown_mode"].slug,
        competition_rows["no_deadline"].slug,
    }


def test_comp_type_filter_accepts_repeated_values_as_or(
    client: TestClient, competition_rows
) -> None:
    """Repeated comp_type params are ORed inside the group, matching company/location."""
    body = client.get(
        "/feed",
        params=[
            ("kind", "competitions"),
            ("location", competition_rows["location"]),
            ("comp_type", "online_coding_challenge"),
            ("comp_type", "case_competition"),
            ("limit", "10"),
        ],
    ).json()

    assert body["total"] == 2
    assert _slugs(body) == {
        competition_rows["online_iit"].slug,
        competition_rows["offline_company"].slug,
    }


def test_registration_filter_maps_free_and_paid(client: TestClient, competition_rows) -> None:
    """registration is a UI label over meta.is_paid, not a separate stored column."""
    free = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "registration": "free",
            "limit": 10,
        },
    ).json()
    paid = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "registration": "paid",
            "limit": 10,
        },
    ).json()

    assert free["total"] == 4
    assert competition_rows["offline_company"].slug not in _slugs(free)
    assert paid["total"] == 1
    assert _slugs(paid) == {competition_rows["offline_company"].slug}


def test_deadline_within_filter_excludes_undated_rows(client: TestClient, competition_rows) -> None:
    """deadline_within means a real future deadline; no deadline is not zero days."""
    three_days = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "deadline_within": 3,
            "limit": 10,
        },
    ).json()
    thirty_days = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "deadline_within": 30,
            "limit": 10,
        },
    ).json()

    assert three_days["total"] == 1
    assert _slugs(three_days) == {competition_rows["online_iit"].slug}
    assert thirty_days["total"] == 3
    assert competition_rows["no_deadline"].slug not in _slugs(thirty_days)
    assert competition_rows["unknown_mode"].slug not in _slugs(thirty_days)


def test_organiser_type_filter_accepts_repeated_values_as_or(
    client: TestClient, competition_rows
) -> None:
    """Organiser type is derived from the company name without duplicating company search."""
    body = client.get(
        "/feed",
        params=[
            ("kind", "competitions"),
            ("location", competition_rows["location"]),
            ("organiser_type", "iit"),
            ("organiser_type", "company"),
            ("limit", "10"),
        ],
    ).json()

    assert body["total"] == 2
    assert _slugs(body) == {
        competition_rows["online_iit"].slug,
        competition_rows["offline_company"].slug,
    }


def test_mode_filter_normalises_storage_and_never_matches_unknown_rows(
    client: TestClient, competition_rows
) -> None:
    """Dirty mode values are excluded from the filterable buckets instead of surfacing."""
    online = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "mode": "online",
            "limit": 10,
        },
    ).json()
    hybrid = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "mode": "hybrid",
            "limit": 10,
        },
    ).json()
    invalid = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "mode": "Jaipur",
            "limit": 10,
        },
    ).json()

    assert online["total"] == 2
    assert _slugs(online) == {
        competition_rows["online_iit"].slug,
        competition_rows["no_deadline"].slug,
    }
    assert hybrid["total"] == 1
    assert _slugs(hybrid) == {competition_rows["hybrid_university"].slug}
    assert invalid["total"] == 0


def test_prize_min_filters_only_inr_prizes_and_excludes_missing_prizes(
    client: TestClient, competition_rows
) -> None:
    """Cash cannot be compared across currency tokens, so only INR-token prizes count."""
    body = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": competition_rows["location"],
            "prize_min": 100000,
            "limit": 10,
        },
    ).json()

    assert body["total"] == 1
    assert _slugs(body) == {competition_rows["online_iit"].slug}
    assert competition_rows["offline_company"].slug not in _slugs(body)
    assert competition_rows["hybrid_university"].slug not in _slugs(body)


def test_competition_filters_and_across_groups(client: TestClient, competition_rows) -> None:
    """Different advanced filter groups combine as AND, leaving one exact match."""
    body = client.get(
        "/feed",
        params=[
            ("kind", "competitions"),
            ("location", competition_rows["location"]),
            ("comp_type", "online_coding_challenge"),
            ("registration", "free"),
            ("deadline_within", "3"),
            ("organiser_type", "iit"),
            ("mode", "online"),
            ("prize_min", "100000"),
            ("limit", "10"),
        ],
    ).json()

    assert body["total"] == 1
    assert _slugs(body) == {competition_rows["online_iit"].slug}


def test_facets_return_counts_and_respect_kind(client: TestClient, competition_rows) -> None:
    """Facet counts must describe the page scope so the UI never offers zero-row pills."""
    competitions = client.get("/facets", params={"kind": "competitions"}).json()
    roles = client.get("/facets", params={"kind": "roles"}).json()

    competition_company = _facet_by_label(
        competitions["company_counts"], competition_rows["iit"].name
    )
    competition_location = _facet_by_label(
        competitions["location_counts"], competition_rows["location"]
    )
    role_company = _facet_by_label(roles["company_counts"], competition_rows["role_company"].name)
    role_location = _facet_by_label(roles["location_counts"], competition_rows["location"])

    assert competition_rows["iit"].name in competitions["companies"]
    assert competition_rows["role_company"].name not in competitions["companies"]
    assert competition_company is not None
    assert competition_company["count"] == 1
    assert competition_location is not None
    assert competition_location["count"] == 5
    assert role_company is not None
    assert role_company["count"] == 1
    assert role_location is not None
    assert role_location["count"] == 1
    assert roles["comp_types"] == []


def test_competition_facets_exclude_unknown_modes_and_count_real_options(
    client: TestClient, competition_rows
) -> None:
    """Mode facets must not leak venue names, while other groups expose counted options."""
    body = client.get("/facets", params={"kind": "competitions"}).json()

    assert _facet_by_value(body["modes"], "unknown") is None
    assert _facet_by_value(body["modes"], "online")["count"] >= 2
    assert _facet_by_value(body["modes"], "offline")["count"] >= 1
    assert _facet_by_value(body["modes"], "hybrid")["count"] >= 1
    assert _facet_by_value(body["comp_types"], "online_coding_challenge")["count"] >= 1
    assert _facet_by_value(body["registrations"], "free")["count"] >= 4
    assert _facet_by_value(body["registrations"], "paid")["count"] >= 1
    assert _facet_by_value(body["deadline_within"], "3")["count"] >= 1
    assert _facet_by_value(body["deadline_within"], "30")["count"] >= 3
    assert _facet_by_value(body["organiser_types"], "iit")["count"] >= 1
    assert _facet_by_value(body["organiser_types"], "company")["count"] >= 1


def test_facets_respect_category_inside_competition_scope(
    client: TestClient, competition_rows
) -> None:
    """category is part of the page scope, so hackathon facets should not count competitions."""
    body = client.get("/facets", params={"category": "hackathon"}).json()

    university = _facet_by_label(body["company_counts"], competition_rows["university"].name)

    assert university is not None
    assert university["count"] == 1
    assert _facet_by_label(body["company_counts"], competition_rows["iit"].name) is None
    assert _facet_by_label(body["company_counts"], competition_rows["role_company"].name) is None
