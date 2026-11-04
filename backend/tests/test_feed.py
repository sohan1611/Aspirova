import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.filters import ROLE_TERMS, STALE_AFTER_DAYS, role_match_expression
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


def test_promoted_surfaces_exclude_stale_rows_but_detail_remains_reachable(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    term = f"stalepromoted{suffix}"
    location_token = f"StalePromotedville-{suffix}"
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"stale-promoted-company-{suffix}",
        name=f"Stale Promoted Company {suffix}",
    )
    stale = models.Opportunity(
        slug=f"stale-promoted-stale-{suffix}",
        title=f"{term} stale role",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/stale/{suffix}",
        posted_at=now - timedelta(days=STALE_AFTER_DAYS + 1),
        deadline=None,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    old_with_future_deadline = models.Opportunity(
        slug=f"stale-promoted-future-deadline-{suffix}",
        title=f"{term} old role with future deadline",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/future/{suffix}",
        posted_at=now - timedelta(days=STALE_AFTER_DAYS + 1),
        deadline=now + timedelta(days=10),
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    unknown_posted_at = models.Opportunity(
        slug=f"stale-promoted-null-posted-at-{suffix}",
        title=f"{term} null posted_at role",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/null-posted-at/{suffix}",
        posted_at=None,
        deadline=None,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    recent = models.Opportunity(
        slug=f"stale-promoted-recent-{suffix}",
        title=f"{term} recent role",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/recent/{suffix}",
        posted_at=now - timedelta(days=30),
        deadline=None,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add_all([company, stale, old_with_future_deadline, unknown_posted_at, recent])
    db_session.flush()

    feed = client.get("/feed", params={"location": location_token, "limit": 10})
    search = client.get("/search", params={"q": term, "limit": 10})
    for_you = client.get(
        "/for-you",
        params={"terms": term, "categories": "job", "limit": 10},
    )
    detail = client.get(f"/opportunity/{stale.slug}")

    assert feed.status_code == 200
    assert search.status_code == 200
    assert for_you.status_code == 200
    expected_promoted_slugs = {
        old_with_future_deadline.slug,
        unknown_posted_at.slug,
        recent.slug,
    }
    assert feed.json()["total"] == 3
    assert {item["slug"] for item in feed.json()["items"]} == expected_promoted_slugs
    assert search.json()["total"] == 3
    assert {item["slug"] for item in search.json()["items"]} == expected_promoted_slugs
    assert for_you.json()["total"] == 3
    assert {item["slug"] for item in for_you.json()["items"]} == expected_promoted_slugs
    assert detail.status_code == 200
    assert detail.json()["slug"] == stale.slug
    assert detail.json()["is_stale"] is True

    current_detail = client.get(f"/opportunity/{old_with_future_deadline.slug}")
    null_posted_at_detail = client.get(f"/opportunity/{unknown_posted_at.slug}")

    assert current_detail.status_code == 200
    assert current_detail.json()["is_stale"] is False
    assert null_posted_at_detail.status_code == 200
    assert null_posted_at_detail.json()["is_stale"] is False


@pytest.mark.parametrize("sort", ["student", "recent", "deadline"])
def test_feed_total_includes_closed_rows_but_open_total_does_not(
    client: TestClient, db_session: Session, sort: str
) -> None:
    suffix = uuid.uuid4().hex
    location_token = f"OpenCountville-{suffix}"
    now = datetime.now(UTC)
    listings = []
    for state, fields in [
        ("open", {}),
        ("future-deadline", {"deadline": now + timedelta(days=5)}),
        ("closed", {"closed_at": now - timedelta(days=1)}),
        ("past-deadline", {"deadline": now - timedelta(days=1)}),
    ]:
        listings.append(
            models.Opportunity(
                slug=f"feed-open-count-{state}-{suffix}",
                title=f"Open count {state} role",
                category="job",
                location=location_token,
                apply_url=f"https://example.com/feed-open-count/{state}/{suffix}",
                status="active",
                first_seen_at=now,
                last_seen_at=now,
                **fields,
            )
        )
    db_session.add_all(listings)
    db_session.flush()

    slugs = []
    for page in range(1, 5):
        response = client.get(
            "/feed",
            params={"location": location_token, "sort": sort, "limit": 1, "page": page},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4
        assert body["open_total"] == 2
        assert body["page"] == page
        assert body["limit"] == 1
        assert len(body["items"]) == 1
        slugs.append(body["items"][0]["slug"])

    assert set(slugs[:2]) == {listing.slug for listing in listings[:2]}
    assert set(slugs[2:]) == {listing.slug for listing in listings[2:]}

    empty = client.get(
        "/feed",
        params={"location": location_token, "sort": sort, "limit": 1, "page": 5},
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
    assert empty.json()["open_total"] == 0


@pytest.mark.parametrize("sort", ["student", "recent", "deadline"])
def test_prefer_country_reorders_without_filtering_or_promoting_closed_rows(
    client: TestClient,
    db_session: Session,
    sort: str,
) -> None:
    suffix = uuid.uuid4().hex
    location = f"CountryPreference-{suffix}"
    now = datetime.now(UTC)
    rows = {}
    for index, (name, country, remote, closed) in enumerate(
        [
            ("foreign-remote", "US", True, False),
            ("foreign-office", "US", False, False),
            ("global-null", None, True, False),
            ("global-blank", "", True, False),
            ("local", "IN", False, False),
            ("closed-local", "IN", False, True),
        ]
    ):
        row = models.Opportunity(
            slug=f"preferred-{name}-{suffix}",
            title="Software Engineer",
            category="job",
            location=location,
            country=country,
            is_remote=remote,
            apply_url=f"https://example.com/preferred/{name}/{suffix}",
            primary_source="greenhouse",
            status="active",
            first_seen_at=now,
            last_seen_at=now - timedelta(minutes=index),
            deadline=now + timedelta(days=index + 1),
            closed_at=now - timedelta(days=1) if closed else None,
        )
        db_session.add(row)
        rows[name] = row
    db_session.flush()
    params = {"location": location, "sort": sort, "limit": 20, "kind": "roles"}
    global_response = client.get("/feed", params=params)
    preferred_response = client.get("/feed", params={**params, "prefer_country": "in"})
    assert global_response.status_code == preferred_response.status_code == 200
    global_body, preferred_body = global_response.json(), preferred_response.json()
    assert global_body["total"] == preferred_body["total"] == 6
    assert global_body["open_total"] == preferred_body["open_total"] == 5
    global_slugs = [item["slug"] for item in global_body["items"]]
    preferred_slugs = [item["slug"] for item in preferred_body["items"]]
    assert set(global_slugs) == set(preferred_slugs)
    assert preferred_slugs[-1] == rows["closed-local"].slug
    if sort == "deadline":
        assert preferred_slugs == global_slugs
    else:
        assert preferred_slugs != global_slugs
        assert preferred_slugs == [
            rows[name].slug
            for name in [
                "local",
                "global-null",
                "global-blank",
                "foreign-remote",
                "foreign-office",
                "closed-local",
            ]
        ]


@pytest.mark.parametrize("country", ["IND", "I", "1N", "", "India"])
def test_prefer_country_rejects_invalid_values(client: TestClient, country: str) -> None:
    assert client.get("/feed", params={"prefer_country": country}).status_code == 422


@pytest.fixture
def role_listings(db_session):
    suffix = uuid.uuid4().hex
    location = f"RoleSignals-{suffix}"
    now = datetime.now(UTC)
    definitions = {
        "missing": ({}, None, 2),
        "unpaid": ({"compensation": {"unpaid": True, "source": "unstop"}}, None, 2),
        "paid": ({"compensation": {"paid": True, "source": "text"}}, None, 2),
        "monthly": (
            {
                "compensation": {"min": 5000, "max": 15000, "currency": "INR", "period": "month"},
                "part_time": True,
                "duration_months": 3,
                "job_offer": True,
            },
            None,
            2,
        ),
        "yearly": (
            {
                "compensation": {"min": 120000, "max": 240000, "currency": "INR", "period": "year"},
                "timing": "part_time",
                "duration_months": 6,
                "offers_ppo": True,
            },
            None,
            5,
        ),
        "foreign": (
            {
                "compensation": {"min": 10000, "max": 20000, "currency": "USD", "period": "month"},
                "duration_months": 12,
            },
            None,
            20,
        ),
        "hourly": ({"compensation": {"max": 500, "currency": "INR", "period": "hour"}}, None, 2),
        "malformed": (
            {
                "compensation": {"max": "unknown", "currency": "INR", "period": "month"},
                "duration_months": "unknown",
            },
            None,
            2,
        ),
        "old-posted": ({}, now - timedelta(days=40), 0),
        "fresh-posted": ({}, now - timedelta(hours=12), 40),
    }
    rows = {}
    for name, (meta, posted_at, first_seen_days) in definitions.items():
        row = models.Opportunity(
            slug=f"role-signals-{name}-{suffix}",
            title="Software Developer Intern",
            title_normalized="software developer intern",
            category="internship",
            location=location,
            country="IN",
            meta=meta,
            posted_at=posted_at,
            apply_url=f"https://example.com/role-signals/{name}/{suffix}",
            status="active",
            first_seen_at=now - timedelta(days=first_seen_days),
            last_seen_at=now,
        )
        db_session.add(row)
        rows[name] = row
    db_session.flush()
    return location, rows


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"paid": "true"}, {"paid", "monthly", "yearly", "foreign", "hourly", "malformed"}),
        ({"paid": "false"}, {"missing", "unpaid", "old-posted", "fresh-posted"}),
        ({"min_stipend": 15000}, {"monthly", "yearly"}),
        ({"min_stipend": 20000}, {"yearly"}),
        ({"min_stipend": 0}, {"monthly", "yearly"}),
        ({"part_time": "true"}, {"monthly", "yearly"}),
        ({"max_duration": 3}, {"monthly"}),
        ({"max_duration": 6}, {"monthly", "yearly"}),
        ({"job_offer": "true"}, {"monthly", "yearly"}),
        ({"posted_within": 1}, {"fresh-posted"}),
        (
            {"posted_within": 3},
            {"missing", "unpaid", "paid", "monthly", "hourly", "malformed", "fresh-posted"},
        ),
        (
            {"posted_within": 7},
            {
                "missing",
                "unpaid",
                "paid",
                "monthly",
                "yearly",
                "hourly",
                "malformed",
                "fresh-posted",
            },
        ),
        (
            {"posted_within": 30},
            {
                "missing",
                "unpaid",
                "paid",
                "monthly",
                "yearly",
                "foreign",
                "hourly",
                "malformed",
                "fresh-posted",
            },
        ),
        ({"paid": "true", "part_time": "true", "max_duration": 3}, {"monthly"}),
    ],
)
def test_feed_role_signal_filters(client, role_listings, params, expected):
    location, rows = role_listings
    response = client.get("/feed", params={"location": location, "limit": 100, **params})
    assert response.status_code == 200
    assert {item["slug"] for item in response.json()["items"]} == {
        rows[name].slug for name in expected
    }


def test_absent_pay_filter_includes_unknown_pay_and_false_only_flags_do_not_filter(
    client, role_listings
):
    location, rows = role_listings
    for params in ({}, {"part_time": "false", "job_offer": "false"}):
        response = client.get("/feed", params={"location": location, "limit": 100, **params})
        assert response.status_code == 200
        assert {item["slug"] for item in response.json()["items"]} == {
            row.slug for row in rows.values()
        }


@pytest.mark.parametrize(
    "role,title",
    [
        ("software", "Software Developer"),
        ("data", "Data Scientist"),
        ("design", "UX Designer"),
        ("marketing", "Marketing Intern"),
        ("finance", "Finance Intern"),
        ("hr", "Recruiter"),
        ("sales", "Sales Intern"),
        ("product", "Product Intern"),
        ("operations", "Operations Intern"),
        ("content", "Content Writer"),
        ("engineering", "Mechanical Engineering Intern"),
        ("research", "Research Intern"),
    ],
)
def test_feed_role_uses_full_text_index(client, db_session, role, title):
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    rows = []
    for index, value in enumerate((title, "Unrelated opportunity")):
        row = models.Opportunity(
            slug=f"role-fts-{index}-{suffix}",
            title=value,
            title_normalized=value.lower(),
            category="internship",
            location=suffix,
            apply_url=f"https://example.com/{suffix}/{index}",
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
        db_session.add(row)
        rows.append(row)
    db_session.flush()
    response = client.get("/feed", params={"location": suffix, "role": role})
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["items"]] == [rows[0].slug]


@pytest.mark.parametrize(
    "params",
    [
        {"posted_within": 2},
        {"posted_within": 0},
        {"posted_within": 31},
        {"role": "unknown"},
        {"role": "software | sales"},
        {"min_stipend": -1},
        {"max_duration": 0},
        {"max_duration": 25},
    ],
)
def test_feed_rejects_invalid_role_filters(client, params):
    assert client.get("/feed", params=params).status_code == 422


@pytest.mark.parametrize("path", ["/feed", "/search"])
@pytest.mark.parametrize("role", ["engineering", "research"])
def test_read_routes_accept_new_domains_and_reject_unknown_roles(client, path, role):
    params = {"role": role, "location": uuid.uuid4().hex}
    if path == "/search":
        params["q"] = "research"
    assert client.get(path, params=params).status_code == 200
    assert client.get(path, params={**params, "role": "unknown"}).status_code == 422


@pytest.mark.parametrize("role", ROLE_TERMS)
def test_role_queries_parse_under_both_text_search_configs(db_session, role):
    for term in ROLE_TERMS[role].split("|"):
        for config in ("english", "simple"):
            assert db_session.scalar(select(func.to_tsquery(config, term.strip()))) is not None


@pytest.mark.parametrize(
    "role,title,matches",
    [
        ("software", "Security Engineer, New Grad", True),
        ("software", "Site Reliability Engineer", True),
        ("software", "Database Engineer Intern", True),
        ("software", "Kernel Engineer - New Grad", True),
        ("software", "Forward Deployed Infrastructure Engineer", True),
        ("software", "Intern Network Engineer", True),
        ("software", "Solutions Engineer intern", True),
        ("software", "Technical Support Engineer", True),
        ("software", "Member of Technical Staff", True),
        ("software", "IT Support Trainee", True),
        ("software", "React Native Internship", True),
        ("software", "SWE Intern", True),
        ("software", "SDET Intern", True),
        ("software", "QA Intern", True),
        ("software", "SRE Intern", True),
        ("software", "Full Stack Intern", True),
        ("software", "Front End Intern", True),
        ("software", "Back End Intern", True),
        ("software", "Cybersecurity Intern", True),
        ("software", "Information Security Intern", True),
        ("software", "Systems Engineer Intern", True),
        ("software", "IT Administrator", True),
        ("software", "Systems Administrator", True),
        ("engineering", "Graduate Engineer Trainee", True),
        ("engineering", "Engineering Intern (Summer 2027)", True),
        ("engineering", "Engineering Internship", True),
        ("engineering", "Intern - Process Engineer", True),
        ("engineering", "Supplier Quality Engineer", True),
        ("engineering", "Project Engineer Intern", True),
        ("software", "Mechanical Engineer", False),
        ("software", "Security Guard", False),
        ("software", "Network Marketing Associate", False),
        ("software", "Customer Support Representative", False),
        ("software", "Business Development Associate", False),
        ("software", "Support Intern", False),
        ("software", "Administrator Intern", False),
        ("software", "Graduate Engineer Trainee", False),
        ("software", "Engineering Intern (Summer 2027)", False),
    ],
)
def test_domain_matching_real_titles(db_session, role, title, matches):
    suffix = uuid.uuid4().hex
    # A software company name must never qualify a non-software title by itself.
    company = models.Company(slug=f"domain-real-{suffix}", name="Software Developers")
    opportunity = models.Opportunity(
        slug=f"domain-real-{suffix}",
        company=company,
        title=title,
        apply_url="https://example.com/apply",
    )
    db_session.add(opportunity)
    db_session.flush()
    matched_id = db_session.scalar(
        select(models.Opportunity.id).where(
            models.Opportunity.id == opportunity.id, role_match_expression(role)
        )
    )
    assert (matched_id == opportunity.id) is matches


def test_search_applies_shared_role_filters(client, role_listings):
    location, rows = role_listings
    response = client.get(
        "/search",
        params={"q": "software", "location": location, "part_time": "true", "max_duration": 3},
    )
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["items"]] == [rows["monthly"].slug]


@pytest.mark.parametrize("also_paid", [False, True])
def test_paid_filter_excludes_explicit_text_unpaid(client, db_session, also_paid):
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    compensation = {"unpaid": True, "source": "text"}
    if also_paid:
        compensation["paid"] = True
    row = models.Opportunity(
        slug=f"text-unpaid-{suffix}",
        title="Software Intern",
        category="internship",
        location=suffix,
        country="IN",
        meta={"compensation": compensation},
        apply_url=f"https://example.com/text-unpaid/{suffix}",
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(row)
    db_session.flush()
    unfiltered = client.get("/feed", params={"location": suffix})
    paid_only = client.get("/feed", params={"location": suffix, "paid": "true"})
    assert unfiltered.status_code == paid_only.status_code == 200
    assert [item["slug"] for item in unfiltered.json()["items"]] == [row.slug]
    assert paid_only.json()["items"] == []
    assert paid_only.json()["total"] == 0
