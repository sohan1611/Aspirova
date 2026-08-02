import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings

LONG_CACHE_CONTROL = "public, max-age=3600, s-maxage=21600, stale-while-revalidate=86400"


class FakeAsyncRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, **_kwargs) -> None:
        self._store[key] = value
        self._ttls[key] = ex


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
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "memory")
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def seeded_programmes(db_session: Session):
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC).replace(microsecond=0)
    current_year = now.year
    last_year = current_year - 1

    alpha = models.Programme(
        slug=f"programme-alpha-{suffix}",
        name=f"Alpha Research Programme {suffix}",
        organiser=f"Alpha Institute {suffix}",
        category="research_internship",
        url=f"https://example.com/programmes/alpha/{suffix}",
        description="Hands-on research mentorship.",
        eligibility="Undergraduate engineering students.",
        typical_window="applications usually open in March",
        country="IN",
        tags=["research", "ai"],
        is_active=True,
    )
    beta = models.Programme(
        slug=f"programme-beta-{suffix}",
        name=f"Beta Open Source Programme {suffix}",
        organiser=f"Needle Org {suffix}",
        category="open_source",
        url=f"https://example.com/programmes/beta/{suffix}",
        description="Open-source mentorship.",
        eligibility="Students and early-career contributors.",
        typical_window="applications usually open in April",
        country="US",
        tags=["open-source"],
        is_active=True,
    )
    gamma = models.Programme(
        slug=f"programme-gamma-{suffix}",
        name=f"Gamma Fellowship {suffix}",
        organiser=f"Gamma Academy {suffix}",
        category="fellowship",
        url=f"https://example.com/programmes/gamma/{suffix}",
        description="Research fellowship.",
        eligibility="Indian students.",
        typical_window="applications usually open in January",
        country="IN",
        tags=["fellowship"],
        is_active=True,
    )
    zeta = models.Programme(
        slug=f"programme-zeta-{suffix}",
        name=f"Zeta Conference {suffix}",
        organiser=f"Zeta Foundation {suffix}",
        category="conference",
        url=f"https://example.com/programmes/zeta/{suffix}",
        description="Annual student conference.",
        eligibility="Students.",
        typical_window="applications usually open in September",
        country=None,
        tags=["conference"],
        is_active=True,
    )
    inactive = models.Programme(
        slug=f"programme-inactive-{suffix}",
        name=f"Inactive Programme {suffix}",
        organiser=f"Inactive Org {suffix}",
        category="government_internship",
        url=f"https://example.com/programmes/inactive/{suffix}",
        description="Retired programme.",
        eligibility="Students.",
        typical_window="retired",
        country="IN",
        tags=["government"],
        is_active=False,
    )

    alpha.editions = [
        models.ProgrammeEdition(
            year=current_year,
            status="expected",
            opens_at=now - timedelta(days=1),
            closes_at=now + timedelta(days=1),
            source_url=f"https://example.com/programmes/alpha/{current_year}/{suffix}",
            verified_at=now - timedelta(days=2),
            notes="Still expected even during the populated date window.",
        ),
        models.ProgrammeEdition(
            year=last_year,
            status="closed",
            opens_at=datetime(last_year, 3, 1, tzinfo=UTC),
            closes_at=datetime(last_year, 3, 31, tzinfo=UTC),
            source_url=f"https://example.com/programmes/alpha/{last_year}/{suffix}",
            verified_at=datetime(last_year, 4, 1, tzinfo=UTC),
            notes="Previous edition.",
        ),
    ]
    beta.editions = [
        models.ProgrammeEdition(
            year=current_year,
            status="open",
            opens_at=now - timedelta(days=3),
            closes_at=now + timedelta(days=10),
            source_url=f"https://example.com/programmes/beta/{current_year}/{suffix}",
            verified_at=now - timedelta(hours=1),
            notes="Verified open.",
        )
    ]
    gamma.editions = [
        models.ProgrammeEdition(
            year=current_year,
            status="announced",
            opens_at=now + timedelta(days=5),
            closes_at=now + timedelta(days=20),
            source_url=f"https://example.com/programmes/gamma/{current_year}/{suffix}",
            verified_at=now,
            notes="Announced, not open.",
        )
    ]
    zeta.editions = [
        models.ProgrammeEdition(
            year=last_year,
            status="closed",
            opens_at=datetime(last_year, 9, 1, tzinfo=UTC),
            closes_at=datetime(last_year, 9, 30, tzinfo=UTC),
            source_url=f"https://example.com/programmes/zeta/{last_year}/{suffix}",
            verified_at=datetime(last_year, 10, 1, tzinfo=UTC),
            notes="No current-year edition yet.",
        )
    ]
    inactive.editions = [
        models.ProgrammeEdition(
            year=current_year,
            status="open",
            opens_at=now - timedelta(days=3),
            closes_at=now + timedelta(days=3),
            source_url=f"https://example.com/programmes/inactive/{current_year}/{suffix}",
            verified_at=now,
            notes="Inactive parent should hide this.",
        )
    ]

    db_session.add_all([alpha, beta, gamma, zeta, inactive])
    db_session.flush()
    return {
        "suffix": suffix,
        "current_year": current_year,
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "zeta": zeta,
        "inactive": inactive,
    }


def _slugs(response: dict) -> list[str]:
    return [item["slug"] for item in response["items"]]


def _last_cache_ttl(fake: FakeAsyncRedis) -> int | None:
    assert fake._ttls
    return list(fake._ttls.values())[-1]


def _create_programme(
    db_session: Session,
    *,
    suffix: str,
    slug: str,
    name: str,
    category: str = "research_internship",
    tags: list[str] | None = None,
) -> models.Programme:
    programme = models.Programme(
        slug=f"programme-{slug}-{suffix}",
        name=f"{name} {suffix}",
        organiser=f"{name} Org {suffix}",
        category=category,
        url=f"https://example.com/programmes/{slug}/{suffix}",
        description="Test programme.",
        eligibility="Students.",
        typical_window=None,
        country="IN",
        tags=tags or ["test"],
        is_active=True,
    )
    db_session.add(programme)
    db_session.flush()
    return programme


def _add_edition(
    db_session: Session,
    programme: models.Programme,
    *,
    year: int,
    status: str,
) -> models.ProgrammeEdition:
    edition = models.ProgrammeEdition(
        programme_id=programme.id,
        year=year,
        status=status,
        source_url=f"{programme.url}/{year}",
        verified_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    db_session.add(edition)
    db_session.flush()
    return edition


def test_programmes_returns_seeded_programmes_with_current_edition(
    client: TestClient, seeded_programmes
) -> None:
    response = client.get(
        "/programmes",
        params={"q": seeded_programmes["suffix"], "limit": 100},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "limit"}
    assert body["total"] == 4
    assert body["page"] == 1
    assert body["limit"] == 100

    names = [item["name"] for item in body["items"]]
    assert names == sorted(names, key=str.lower)

    by_slug = {item["slug"]: item for item in body["items"]}
    alpha = by_slug[seeded_programmes["alpha"].slug]
    assert alpha["current_edition"]["year"] == seeded_programmes["current_year"]
    assert alpha["current_edition"]["status"] == "expected"
    assert alpha["description"] == "Hands-on research mentorship."
    assert alpha["tags"] == ["research", "ai"]

    zeta = by_slug[seeded_programmes["zeta"].slug]
    assert zeta["current_edition"]["year"] == seeded_programmes["current_year"] - 1
    assert zeta["current_edition"]["status"] == "closed"
    assert seeded_programmes["inactive"].slug not in by_slug


def test_highest_non_discontinued_year_is_current_for_list_and_detail(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    programme = _create_programme(
        db_session,
        suffix=suffix,
        slug="multi-year",
        name="Multi Year Programme",
    )
    _add_edition(db_session, programme, year=2026, status="closed")
    _add_edition(db_session, programme, year=2027, status="announced")

    listing = client.get(
        "/programmes",
        params={"q": programme.name, "status": "announced"},
    )
    closed_filter = client.get(
        "/programmes",
        params={"q": programme.name, "status": "closed"},
    )
    detail = client.get(f"/programme/{programme.slug}")

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["current_edition"]["year"] == 2027
    assert listing.json()["items"][0]["current_edition"]["status"] == "announced"

    assert closed_filter.status_code == 200
    assert closed_filter.json()["total"] == 0
    assert closed_filter.json()["items"] == []

    assert detail.status_code == 200
    assert detail.json()["current_edition"]["year"] == 2027
    assert detail.json()["current_edition"]["status"] == "announced"


def test_expected_only_edition_is_current(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    programme = _create_programme(
        db_session,
        suffix=suffix,
        slug="expected-only",
        name="Expected Only Programme",
    )
    _add_edition(db_session, programme, year=2026, status="expected")

    listing = client.get("/programmes", params={"q": programme.name})
    detail = client.get(f"/programme/{programme.slug}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["current_edition"]["year"] == 2026
    assert listing.json()["items"][0]["current_edition"]["status"] == "expected"
    assert detail.status_code == 200
    assert detail.json()["current_edition"]["year"] == 2026
    assert detail.json()["current_edition"]["status"] == "expected"


def test_discontinued_highest_year_is_not_current(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    programme = _create_programme(
        db_session,
        suffix=suffix,
        slug="discontinued-highest",
        name="Discontinued Highest Programme",
    )
    _add_edition(db_session, programme, year=2026, status="closed")
    _add_edition(db_session, programme, year=2027, status="discontinued")

    listing = client.get("/programmes", params={"q": programme.name})
    detail = client.get(f"/programme/{programme.slug}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["current_edition"]["year"] == 2026
    assert listing.json()["items"][0]["current_edition"]["status"] == "closed"
    assert detail.status_code == 200
    assert detail.json()["current_edition"]["year"] == 2026
    assert detail.json()["current_edition"]["status"] == "closed"


def test_programme_with_no_editions_has_null_current_edition(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    programme = _create_programme(
        db_session,
        suffix=suffix,
        slug="no-editions",
        name="No Editions Programme",
    )

    listing = client.get("/programmes", params={"q": programme.name})
    detail = client.get(f"/programme/{programme.slug}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["current_edition"] is None
    assert detail.status_code == 200
    assert detail.json()["current_edition"] is None


def test_programme_filters_narrow_correctly(client: TestClient, seeded_programmes) -> None:
    suffix = seeded_programmes["suffix"]

    category = client.get(
        "/programmes",
        params={"q": suffix, "category": "research_internship"},
    )
    country = client.get("/programmes", params={"q": suffix, "country": "in"})
    status = client.get("/programmes", params={"q": suffix, "status": "open"})
    query = client.get("/programmes", params={"q": f"needle org {suffix}"})
    invalid_category = client.get("/programmes", params={"category": "not-a-category"})

    assert category.status_code == 200
    assert _slugs(category.json()) == [seeded_programmes["alpha"].slug]

    assert country.status_code == 200
    assert set(_slugs(country.json())) == {
        seeded_programmes["alpha"].slug,
        seeded_programmes["gamma"].slug,
    }

    assert status.status_code == 200
    assert _slugs(status.json()) == [seeded_programmes["beta"].slug]

    assert query.status_code == 200
    assert _slugs(query.json()) == [seeded_programmes["beta"].slug]

    assert invalid_category.status_code == 422


def test_programmes_pagination_total_and_no_repeated_page_items(
    client: TestClient, seeded_programmes
) -> None:
    params = {"q": seeded_programmes["suffix"], "limit": 1}
    first = client.get("/programmes", params={**params, "page": 1})
    second = client.get("/programmes", params={**params, "page": 2})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["total"] == 4
    assert second.json()["total"] == 4
    assert _slugs(first.json()) != _slugs(second.json())


def test_programme_divisions_rank_without_filtering_and_report_match_count(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    unmatched = _create_programme(
        db_session,
        suffix=suffix,
        slug="aardvark-unmatched",
        name="Aardvark Unmatched Programme",
        tags=["test"],
    )
    matched = _create_programme(
        db_session,
        suffix=suffix,
        slug="zulu-cs",
        name="Zulu CS Programme",
        tags=["cs", "coding", "research"],
    )

    base = client.get("/programmes", params={"q": suffix, "limit": 100})
    ranked = client.get("/programmes", params={"q": suffix, "divisions": "cse", "limit": 100})

    assert base.status_code == 200
    assert ranked.status_code == 200
    assert base.json()["total"] == ranked.json()["total"] == 2
    assert _slugs(base.json()) == [unmatched.slug, matched.slug]
    assert _slugs(ranked.json()) == [matched.slug, unmatched.slug]
    assert [item["match_count"] for item in base.json()["items"]] == [0, 0]

    ranked_by_slug = {item["slug"]: item for item in ranked.json()["items"]}
    assert ranked_by_slug[matched.slug]["match_count"] == 2
    assert ranked_by_slug[unmatched.slug]["match_count"] == 0


def test_programme_divisions_unknown_key_is_ignored(
    client: TestClient,
    seeded_programmes,
) -> None:
    params = {"q": seeded_programmes["suffix"], "limit": 100}
    base = client.get("/programmes", params=params)
    unknown = client.get(
        "/programmes",
        params={**params, "divisions": "unknown_division"},
    )

    assert base.status_code == 200
    assert unknown.status_code == 200
    assert _slugs(unknown.json()) == _slugs(base.json())
    assert [item["match_count"] for item in unknown.json()["items"]] == [0, 0, 0, 0]


def test_programme_divisions_empty_tag_mapping_keeps_existing_order(
    client: TestClient,
    seeded_programmes,
) -> None:
    params = {"q": seeded_programmes["suffix"], "limit": 100}
    base = client.get("/programmes", params=params)
    empty_mapping = client.get(
        "/programmes",
        params={**params, "divisions": "marketing"},
    )

    assert base.status_code == 200
    assert empty_mapping.status_code == 200
    assert _slugs(empty_mapping.json()) == _slugs(base.json())
    assert [item["match_count"] for item in empty_mapping.json()["items"]] == [0, 0, 0, 0]


def test_programme_divisions_preserve_category_filter(
    client: TestClient,
    seeded_programmes,
) -> None:
    response = client.get(
        "/programmes",
        params={
            "q": seeded_programmes["suffix"],
            "category": "open_source",
            "divisions": "cse",
            "limit": 100,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert _slugs(body) == [seeded_programmes["beta"].slug]
    assert body["items"][0]["match_count"] == 1


def test_programme_divisions_do_not_change_expected_status(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    unmatched = _create_programme(
        db_session,
        suffix=suffix,
        slug="aardvark-open",
        name="Aardvark Open Programme",
        tags=["test"],
    )
    matched_expected = _create_programme(
        db_session,
        suffix=suffix,
        slug="zulu-expected-cs",
        name="Zulu Expected CS Programme",
        tags=["cs"],
    )
    _add_edition(db_session, unmatched, year=2026, status="open")
    _add_edition(db_session, matched_expected, year=2026, status="expected")

    response = client.get("/programmes", params={"q": suffix, "divisions": "cse"})

    assert response.status_code == 200
    first = response.json()["items"][0]
    assert first["slug"] == matched_expected.slug
    assert first["match_count"] == 1
    assert first["current_edition"]["status"] == "expected"


def test_inactive_programmes_are_excluded(client: TestClient, seeded_programmes) -> None:
    response = client.get(
        "/programmes",
        params={"q": f"Inactive Programme {seeded_programmes['suffix']}"},
    )
    detail = client.get(f"/programme/{seeded_programmes['inactive'].slug}")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []
    assert detail.status_code == 404


def test_programme_detail_returns_all_editions_newest_first(
    client: TestClient, seeded_programmes
) -> None:
    response = client.get(f"/programme/{seeded_programmes['alpha'].slug}")
    unknown = client.get("/programme/unknown-programme-slug")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == seeded_programmes["alpha"].slug
    assert body["description"] == "Hands-on research mentorship."
    assert body["eligibility"] == "Undergraduate engineering students."
    assert [edition["year"] for edition in body["editions"]] == [
        seeded_programmes["current_year"],
        seeded_programmes["current_year"] - 1,
    ]
    assert body["current_edition"]["status"] == "expected"

    assert unknown.status_code == 404


def test_expected_status_is_not_inferred_open_from_dates(
    client: TestClient, seeded_programmes
) -> None:
    listing = client.get(
        "/programmes",
        params={"q": f"Alpha Research Programme {seeded_programmes['suffix']}"},
    )
    detail = client.get(f"/programme/{seeded_programmes['alpha'].slug}")

    assert listing.status_code == 200
    assert detail.status_code == 200
    edition = listing.json()["items"][0]["current_edition"]
    assert datetime.fromisoformat(edition["opens_at"]) <= datetime.now(UTC)
    assert datetime.fromisoformat(edition["closes_at"]) >= datetime.now(UTC)
    assert edition["status"] == "expected"
    assert detail.json()["current_edition"]["status"] == "expected"
    assert detail.json()["editions"][0]["status"] == "expected"


def test_frontend_research_clock_inference_source_does_not_return() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    frontend = repo_root / "frontend"
    if not frontend.exists():
        pytest.skip("frontend directory is not present")

    assert not (frontend / "lib" / "researchPrograms.ts").exists()
    assert not (frontend / "components" / "ResearchProgramCard.tsx").exists()

    ignored_dirs = {"node_modules", ".next", "out", "coverage"}
    forbidden = ("isApplyWindowLikelyOpen", "applyWindow")
    matches: list[str] = []
    for path in frontend.rglob("*"):
        if not path.is_file() or ignored_dirs.intersection(path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in forbidden:
            if needle in text:
                matches.append(f"{path.relative_to(repo_root)} contains {needle}")

    assert matches == []


def test_programme_tag_map_matches_taxonomy_and_registry_vocabulary() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    frontend = repo_root / "frontend"
    if not frontend.exists():
        pytest.skip("frontend directory is not present")

    taxonomy = json.loads((frontend / "lib" / "taxonomy.json").read_text(encoding="utf-8"))
    programme_tag_map = json.loads(
        (repo_root / "backend" / "data" / "programme_tag_map.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (repo_root / "backend" / "data" / "programmes.json").read_text(encoding="utf-8")
    )

    division_keys = {
        division["key"]
        for stream in taxonomy["streams"]
        for division in stream.get("divisions", [])
    }
    registry_tags = {
        tag for programme in registry["programmes"] for tag in programme.get("tags", [])
    }
    mapped_tags = {tag for tags in programme_tag_map["divisions"].values() for tag in tags}

    assert set(programme_tag_map["divisions"]) <= division_keys
    assert mapped_tags <= registry_tags


def test_programme_routes_carry_long_cache_control(
    client: TestClient, seeded_programmes, monkeypatch
) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    assert middleware._is_long_cache_path("/programmes")
    assert middleware._is_long_cache_path(f"/programme/{seeded_programmes['alpha'].slug}")
    assert middleware._is_cacheable("/programmes")
    assert middleware._is_cacheable(f"/programme/{seeded_programmes['alpha'].slug}")

    listing = client.get(
        "/programmes",
        params={"q": seeded_programmes["suffix"]},
        headers={"X-Forwarded-For": "203.0.113.130"},
    )
    detail = client.get(
        f"/programme/{seeded_programmes['alpha'].slug}",
        headers={"X-Forwarded-For": "203.0.113.131"},
    )

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert listing.headers["Cache-Control"] == LONG_CACHE_CONTROL
    assert detail.headers["Cache-Control"] == LONG_CACHE_CONTROL
    assert listing.headers["X-Cache"] == "MISS"
    assert detail.headers["X-Cache"] == "MISS"
    assert all(ttl == get_settings().long_cache_ttl_seconds for ttl in fake._ttls.values())
    assert _last_cache_ttl(fake) == get_settings().long_cache_ttl_seconds


def test_programme_routes_are_rate_limited(
    client: TestClient, seeded_programmes, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_ip_opportunity_per_minute", 1)

    list_headers = {"X-Forwarded-For": "203.0.113.132"}
    list_first = client.get(
        "/programmes",
        params={"q": seeded_programmes["suffix"]},
        headers=list_headers,
    )
    list_second = client.get(
        "/programmes",
        params={"q": seeded_programmes["suffix"], "page": 2},
        headers=list_headers,
    )

    detail_headers = {"X-Forwarded-For": "203.0.113.133"}
    detail_first = client.get(
        f"/programme/{seeded_programmes['alpha'].slug}",
        headers=detail_headers,
    )
    detail_second = client.get(
        f"/programme/{seeded_programmes['alpha'].slug}",
        headers=detail_headers,
    )

    assert list_first.status_code == 200
    assert list_second.status_code == 429
    assert int(list_second.headers["Retry-After"]) >= 0
    assert detail_first.status_code == 200
    assert detail_second.status_code == 429
    assert int(detail_second.headers["Retry-After"]) >= 0
