import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.main import app
from api.company import company_search_matches
from api.search_related import (
    RelatedCompanies,
    RelatedProgrammes,
    related_companies,
    related_programmes,
    search_related,
)
from api.schemas import CompanyListItem
from core import models
from core.cache import reset_l1_cache
from core.calendar_public import current_calendar_item


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
def client(db_session, monkeypatch):
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def empty_listing_client(monkeypatch):
    """Exercise request validation/short-query behavior without a database."""
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    empty_db = SimpleNamespace(
        execute=lambda _statement: SimpleNamespace(all=lambda: []),
        scalar=lambda _statement: 0,
    )
    app.dependency_overrides[get_db] = lambda: empty_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def programme(slug, name, **kwargs):
    return models.Programme(
        slug=slug,
        name=name,
        organiser="Google",
        category="open_source",
        country="IN",
        url="https://summerofcode.withgoogle.com/",
        **kwargs,
    )


def test_current_calendar_item_retains_calendar_basis_and_precision():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    item = programme(
        "test-current-selection",
        "Test Fellowship",
        editions=[
            models.ProgrammeEdition(year=2026, status="closed"),
            models.ProgrammeEdition(
                year=2027, status="expected", opens_at=datetime(2027, 2, 1, tzinfo=UTC)
            ),
            models.ProgrammeEdition(year=2028, status="expected"),
        ],
    )
    selected = current_calendar_item(item, now)
    assert selected.edition.year == 2027
    assert selected.edition.basis == "tentative"
    assert selected.edition.opens_precision == "month"
    item.editions[1].status = "announced"
    selected = current_calendar_item(item, now)
    assert selected.edition.basis == "official"
    assert selected.edition.opens_precision == "day"


def test_current_calendar_item_latest_registry_fallback_and_no_edition():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    item = programme(
        "test-undated-selection",
        "Undated Fellowship",
        editions=[
            models.ProgrammeEdition(year=2027, status="expected"),
            models.ProgrammeEdition(year=2028, status="discontinued"),
        ],
    )
    assert current_calendar_item(item, now).edition.year == 2027
    item.editions.clear()
    assert current_calendar_item(item, now) is None


def test_acronym_programmes_pagination_and_calendar(client, db_session):
    suffix = uuid.uuid4().hex
    gsoc = programme(f"google-summer-{suffix}", "Google Summer of Code")
    gsoc.editions = [
        models.ProgrammeEdition(
            year=datetime.now(UTC).year + 1,
            status="expected",
            opens_at=datetime.now(UTC) + timedelta(days=60),
        )
    ]
    db_session.add(gsoc)
    db_session.flush()
    response = client.get(
        "/programmes", params={"q": "gsoc", "country": "IN", "status": "expected", "limit": 1}
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["slug"] == gsoc.slug
    assert (
        client.get("/programmes", params={"q": "gsoc", "page": 100}).json()["total"]
        == response.json()["total"]
    )
    assert (
        client.get("/programmes", params={"q": "gsoc", "category": "government_exam"}).json()[
            "total"
        ]
        == 0
    )
    today = datetime.now(UTC).date()
    calendar = client.get(
        "/calendar",
        params={
            "q": "gsoc",
            "from": today.isoformat(),
            "to": (today + timedelta(days=365)).isoformat(),
        },
    )
    assert calendar.status_code == 200
    assert gsoc.slug in {item["programme"]["slug"] for item in calendar.json()["items"]}


def test_company_acronym_exact_and_substring_fallback(client, db_session):
    suffix = uuid.uuid4().hex
    companies = [
        models.Company(slug=f"entity-{index}-{suffix}", name=name)
        for index, name in enumerate(
            [
                "Reserve Bank of India",
                "Reflect Orbital",
                "Loftorbital",
                "Microsoft",
                "Microsoft Research",
            ]
        )
    ]
    db_session.add_all(companies)
    db_session.flush()
    rbi = client.get("/companies/search", params={"q": "rbi"}).json()
    assert rbi[0]["name"] == "Reserve Bank of India"
    assert not {"Reflect Orbital", "Loftorbital"} & {item["name"] for item in rbi}
    assert (
        client.get("/companies/search", params={"q": "microsoft"}).json()[0]["name"] == "Microsoft"
    )
    assert {"Reflect Orbital", "Loftorbital"} <= {
        item["name"] for item in client.get("/companies/search", params={"q": "orbit"}).json()
    }


def test_related_shape_editions_counts_sources_and_inactive_companies(client, db_session):
    token = "related" + uuid.uuid4().hex
    now = datetime.now(UTC)
    employer = models.Company(slug=token, name=token)
    empty_prefix = models.Company(slug=token + "-empty", name=token + " Research")
    prog = programme(token, token + " Programme", company=employer)
    prog.editions = [
        models.ProgrammeEdition(year=now.year - 1, status="closed"),
        models.ProgrammeEdition(
            year=now.year,
            status="open",
            opens_at=now - timedelta(days=5),
            closes_at=now + timedelta(days=5),
        ),
        models.ProgrammeEdition(
            year=now.year + 1, status="expected", opens_at=now + timedelta(days=80)
        ),
    ]
    db_session.add_all([employer, empty_prefix, prog])
    for index, source in enumerate(["greenhouse", "unstop", "remoteok", "devpost", "jobicy", None]):
        db_session.add(
            models.Opportunity(
                slug=f"{token}-{index}",
                title=f"{token} intern",
                title_normalized=f"{token} intern",
                company=employer,
                category="internship",
                status="active",
                primary_source=source,
                apply_url=f"https://example.com/{token}/{index}",
                last_seen_at=now,
            )
        )
    db_session.flush()
    response = client.get("/search/related", params={"q": f" {token} "})
    assert response.status_code == 200
    body = response.json()
    assert body["q"] == token
    assert body["programmes"]["total"] == 1
    item = body["programmes"]["items"][0]
    assert item["entity_type"] == "programme" and item["match"] == "slug"
    assert item["path"] == f"/programme/{token}"
    assert item["calendar_path"] == f"/calendar?item={quote(f'{token}:{now.year}:0', safe='')}"
    assert item["deadline_rolling"] is False
    assert item["official_url"] == prog.url
    assert item["edition"]["status"] == "open" and item["edition"]["basis"] == "official"
    assert len(body["companies"]["items"]) == 1
    assert body["companies"]["items"][0]["active_count"] == 6
    assert body["companies"]["items"][0]["entity_type"] == "company"
    assert body["companies"]["items"][0]["path"] == f"/companies/{token}"
    assert (
        body["listings"]["total"] == client.get("/search", params={"q": token}).json()["total"] == 6
    )
    assert sum(source["count"] for source in body["listings"]["by_source"]) == 6
    assert {row["value"]: row["count"] for row in body["listings"]["by_source"]} == {
        "direct": 1,
        "unstop": 1,
        "remoteok": 1,
        "devpost": 1,
        "other": 2,
    }
    exact_empty = client.get("/search/related", params={"q": empty_prefix.name}).json()
    assert exact_empty["companies"]["items"][0]["active_count"] == 0
    # No FTS hit for the typo: both endpoints must take the same trigram fallback.
    typo = token + "x"
    fallback = client.get("/search/related", params={"q": typo}).json()["listings"]
    assert fallback["total"] == client.get("/search", params={"q": typo}).json()["total"] == 6
    assert sum(row["count"] for row in fallback["by_source"]) == fallback["total"]


def test_company_domain_dedupe_keeps_best_and_null_domains(monkeypatch):
    # The DB has a partial unique index on non-null domains; exercise spelling
    # variants defensively at this boundary without weakening that constraint.
    def company(slug, name, domain, count):
        return CompanyListItem(slug=slug, name=name, domain=domain, active_count=count)

    monkeypatch.setattr(
        "api.search_related.company_search_matches",
        lambda *_args, **_kwargs: [
            (company("best", "Microsoft", "Microsoft.com", 1), "exact"),
            (company("duplicate", "Microsoft Research", "microsoft.com", 20), "prefix"),
            (company("null-1", "Microsoft India", None, 2), "prefix"),
            (company("null-2", "Microsoft Labs", None, 1), "prefix"),
            (company("inactive", "Microsoft Club", None, 0), "prefix"),
        ],
    )
    result = related_companies(None, "microsoft")
    assert result.total == 3
    assert [item.slug for item in result.items] == ["best", "null-1", "null-2"]


def test_company_name_dedupe_keeps_the_row_with_more_open_roles(monkeypatch):
    # Programme seeding can create a second company row with the same name and no domain.
    def company(slug, name, domain, count):
        return CompanyListItem(slug=slug, name=name, domain=domain, active_count=count)

    monkeypatch.setattr(
        "api.search_related.company_search_matches",
        lambda *_args, **_kwargs: [
            (company("rbi-with-roles", "Reserve Bank of India", "rbi.org.in", 4), "acronym"),
            (company("rbi-registry", "Reserve Bank of India", None, 0), "acronym"),
            (company("rbi-spelling", "Reserve Bank of India.", None, 0), "acronym"),
        ],
    )
    result = related_companies(None, "rbi")
    assert [item.slug for item in result.items] == ["rbi-with-roles"]
    assert result.total == 1


def test_related_company_path_is_url_safe(monkeypatch):
    company = CompanyListItem(slug="space / café", name="Microsoft", active_count=0)
    monkeypatch.setattr(
        "api.search_related.company_search_matches", lambda *_args, **_kwargs: [(company, "exact")]
    )
    assert (
        related_companies(None, "microsoft").items[0].path == "/companies/space%20%2F%20caf%C3%A9"
    )


def test_company_search_counts_only_python_matched_ids_unit():
    class FakeDB:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            rows = (
                [
                    SimpleNamespace(
                        id=11, slug="rbi", name="Reserve Bank of India", domain=None, logo_url=None
                    ),
                    SimpleNamespace(
                        id=22, slug="unrelated", name="Reflect Orbital", domain=None, logo_url=None
                    ),
                ]
                if len(self.statements) == 1
                else [(11, 3)]
            )
            return SimpleNamespace(all=lambda: rows)

    db = FakeDB()
    matches = company_search_matches(db, "rbi")
    assert len(db.statements) == 2
    assert matches[0][0].active_count == 3 and matches[0][1] == "acronym"
    candidate_sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "JOIN" not in candidate_sql and "opportunities" not in candidate_sql
    counts = db.statements[1].compile(dialect=postgresql.dialect())
    assert "opportunities.company_id IN" in str(counts)
    assert counts.params["company_id_1"] == [11]


@pytest.mark.parametrize(
    "fts_rows,expected_queries,expected_total", [([("direct", 7)], 1, 7), ([], 2, 2)]
)
def test_related_grouped_counts_try_fts_then_only_fallback_when_empty(
    monkeypatch, fts_rows, expected_queries, expected_total
):
    monkeypatch.setattr(
        "api.search_related.related_programmes", lambda *_: RelatedProgrammes(total=0, items=[])
    )
    monkeypatch.setattr(
        "api.search_related.related_companies", lambda *_: RelatedCompanies(total=0, items=[])
    )

    class FakeDB:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            return SimpleNamespace(
                all=lambda: fts_rows if len(self.statements) == 1 else [("other", 2)]
            )

    db = FakeDB()
    result = search_related(q="engineer", db=db)
    assert result.listings.total == expected_total
    assert len(db.statements) == expected_queries
    first = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "@@" in first and "GROUP BY" in first
    if expected_queries == 2:
        second = str(db.statements[1].compile(dialect=postgresql.dialect()))
        assert "similarity(" in second and "GROUP BY" in second


def test_company_search_two_queries_count_only_matched_candidate_ids(client, db_session):
    token = "bounded" + uuid.uuid4().hex
    match = models.Company(slug=token, name=f"{token} Labs")
    substring = models.Company(slug=token + "-substring", name=f"The {token} Company")
    false_positive = models.Company(slug=token + "-false", name="Banana Institute")
    db_session.add_all([match, substring, false_positive])
    db_session.flush()
    db_session.add(
        models.Opportunity(
            slug=token + "-listing",
            title="Intern",
            company=match,
            category="internship",
            status="active",
            apply_url=f"https://example.com/{token}",
        )
    )
    db_session.flush()
    statements = []

    def capture(_conn, _cursor, statement, params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, params))

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        response = client.get("/companies/search", params={"q": token})
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert response.status_code == 200
    # The follow-company search keeps substring rows, ranked after the prefix match.
    assert [item["slug"] for item in response.json()] == [match.slug, substring.slug]
    assert len(statements) == 2
    assert "JOIN" not in statements[0][0] and "opportunities" not in statements[0][0]
    count_sql, params = statements[1]
    assert "opportunities.company_id IN" in count_sql and "JOIN" not in count_sql
    assert {value for key, value in params.items() if key.startswith("company_id_")} == {
        match.id,
        substring.id,
    }


def test_related_drops_substring_companies_when_a_stronger_match_exists(monkeypatch):
    def company(slug, name, count):
        return CompanyListItem(slug=slug, name=name, active_count=count)

    rows = [
        (company("research-triangle", "Research Triangle", 2), "prefix"),
        (company("microsoft-research", "Microsoft Research", 9), "substring"),
    ]
    monkeypatch.setattr(
        "api.search_related.company_search_matches", lambda *_args, **_kwargs: list(rows)
    )
    assert [item.slug for item in related_companies(None, "research").items] == [
        "research-triangle"
    ]
    rows.pop(0)
    assert [item.slug for item in related_companies(None, "research").items] == [
        "microsoft-research"
    ]


def test_related_programme_calendar_deep_link_and_rolling_metadata():
    from tests.test_hiring_calendar import source_programme

    class FakeDB:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, _statement):
            return self

        def unique(self):
            return self

        def scalars(self):
            return self

        def all(self):
            return self.rows

    rolling = source_programme("microsoft-swe-india")
    rolling.company = None
    result = related_programmes(FakeDB([rolling]), "microsoft").items[0]
    assert result.deadline_rolling is True
    assert result.calendar_path.startswith("/calendar?item=")
    undated = programme("undated-search", "Undated Fellowship", editions=[])
    item = related_programmes(FakeDB([undated]), "undated").items[0]
    assert item.edition is None and item.deadline_rolling is False
    assert item.calendar_path == "/calendar?q=Undated%20Fellowship"


def test_related_constant_queries_one_vs_many(client, db_session):
    token = "constant" + uuid.uuid4().hex
    connection = db_session.connection()

    def count_request(q):
        statements = []

        def track(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        reset_l1_cache()
        event.listen(connection, "before_cursor_execute", track)
        try:
            assert client.get("/search/related", params={"q": q}).status_code == 200
        finally:
            event.remove(connection, "before_cursor_execute", track)
        return len(statements)

    for count in (1, 40):
        db_session.add_all(
            [
                programme(
                    f"{token}-{count}-{i}",
                    f"{token} Programme {count} {i}",
                    editions=[models.ProgrammeEdition(year=2027, status="expected")],
                )
                for i in range(count)
            ]
        )
        db_session.flush()
        for i in range(count):
            db_session.add(
                models.Opportunity(
                    slug=f"{token}-listing-{count}-{i}",
                    title=f"{token} intern",
                    title_normalized=f"{token} intern",
                    category="internship",
                    apply_url=f"https://example.com/{token}/{count}/{i}",
                    status="active",
                )
            )
        db_session.flush()
        db_session.expire_all()
        assert count_request(token) == 4
        assert count_request(token + "x") == 5
        assert count_request("missing" + uuid.uuid4().hex) == 5


def test_related_limits_and_order_and_zero_active_acronym(client, db_session):
    token = "ranked" + uuid.uuid4().hex
    now = datetime.now(UTC)
    programmes = [
        programme(
            f"{token}-{index}",
            f"{token} Programme {index}",
            editions=[
                models.ProgrammeEdition(
                    year=now.year + 1,
                    status="expected" if index < 4 else "announced",
                    opens_at=now + timedelta(days=30),
                ),
            ],
        )
        for index in range(6)
    ]
    companies = [
        models.Company(slug=f"{token}-{index}", name=f"{token} Company {index}")
        for index in range(5)
    ]
    for index, employer in enumerate(companies):
        db_session.add_all(
            [
                models.Opportunity(
                    slug=f"{token}-{index}-{i}",
                    title="Intern",
                    category="internship",
                    company=employer,
                    status="active",
                    apply_url=f"https://example.com/{token}/{index}/{i}",
                )
                for i in range(index + 1)
            ]
        )
    db_session.add_all(programmes + companies)
    db_session.add(models.Company(slug=f"{token}-rbi", name="Reserve Bank of India"))
    db_session.flush()
    body = client.get("/search/related", params={"q": token}).json()
    assert body["programmes"]["total"] == 6 and len(body["programmes"]["items"]) == 4
    assert [item["edition"]["status"] for item in body["programmes"]["items"]] == [
        "announced",
        "announced",
        "expected",
        "expected",
    ]
    assert body["companies"]["total"] == 5 and len(body["companies"]["items"]) == 3
    assert [item["active_count"] for item in body["companies"]["items"]] == [5, 4, 3]
    rbi = client.get("/search/related", params={"q": "rbi"}).json()["companies"]["items"][0]
    assert rbi["match"] == "acronym" and rbi["active_count"] == 0


def test_related_inherits_search_cache_and_rate_limit(client, db_session, monkeypatch):
    from core.config import get_settings

    token = "cached" + uuid.uuid4().hex
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(settings, "rate_limit_ip_feed_search_per_minute", 2)
    monkeypatch.setattr(settings, "l1_cache_enabled", True)
    first = client.get("/search/related", params={"q": token})
    second = client.get("/search/related", params={"q": token})
    assert first.status_code == second.status_code == 200
    assert first.headers["X-Cache"] == "MISS" and second.headers["X-Cache"] == "HIT"
    assert (
        first.headers["Cache-Control"]
        == "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"
    )
    # Search and related share the same per-IP allowance, including cached reads.
    assert client.get("/search", params={"q": token}).status_code == 429


@pytest.mark.parametrize("q", ["", " ", "\t\n", "a" * 201])
def test_related_rejects_invalid_q(client, q):
    assert client.get("/search/related", params={"q": q}).status_code == 422


@pytest.mark.parametrize("q", [" ", "\t\n", "   \t "])
def test_existing_search_keeps_whitespace_query_contract(empty_listing_client, q):
    response = empty_listing_client.get("/search", params={"q": q})
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0


@pytest.mark.parametrize("q", ["m", " M— ", "%"])
def test_related_short_normalized_query_omits_entities(empty_listing_client, monkeypatch, q):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Short normalized queries must not load entities")

    monkeypatch.setattr("api.search_related.related_programmes", unexpected)
    monkeypatch.setattr("api.search_related.related_companies", unexpected)
    response = empty_listing_client.get("/search/related", params={"q": q})
    assert response.status_code == 200
    body = response.json()
    assert body["programmes"] == body["companies"] == {"total": 0, "items": []}
    assert (
        body["listings"]["total"]
        == empty_listing_client.get("/search", params={"q": q}).json()["total"]
    )
