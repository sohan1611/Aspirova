import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from api import feed, middleware
from api.deps import get_db
from api.filters import pay_rank_expression
from api.main import app
from core import models
from core.pay_format import (
    INR_PER_UNIT,
    MAX_PLAUSIBLE_HOURLY_INR,
    MAX_PLAUSIBLE_MONTHLY_INR,
    PERIOD_TO_MONTH,
    monthly_inr_equivalent,
)


def compensation(**overrides):
    return {"max": 100, "currency": "INR", "period": "month", **overrides}


@pytest.mark.parametrize("currency,fx", INR_PER_UNIT.items())
@pytest.mark.parametrize("period,factor", PERIOD_TO_MONTH.items())
def test_monthly_equivalent_currencies_and_periods(currency, fx, period, factor):
    meta = {"compensation": compensation(currency=currency, period=period, max=10)}
    assert monthly_inr_equivalent(meta) == pytest.approx(10 * factor * fx)


@pytest.mark.parametrize(
    "pay,expected",
    [
        (compensation(min=50, max=100), 100),
        ({"min": 50, "currency": "INR", "period": "month"}, 50),
        (compensation(min=50, max=0), 50),
        (compensation(min=50, max=-1), 50),
        (compensation(min=50, max="80k"), 50),
        (compensation(min=50, max=True), 50),
        (compensation(unpaid=True), None),
        (compensation(unpaid="true"), 100),
        ({"paid": True}, None),
        (compensation(currency="JPY"), None),
        (compensation(period="week"), None),
        (compensation(currency="USD", period="hour", max=800), None),
        (compensation(currency="USD", period="hour", max=50), 50 * 173 * 88),
        (compensation(max=5_000_000), 5_000_000),
        (compensation(max=20_000_000), None),
        (compensation(currency="USD", period="year", max=5_000_000), None),
        (
            compensation(currency="USD", period="year", max=395_500),
            395_500 / 12 * 88,
        ),
        (compensation(max="80k"), None),
        (compensation(max=True, min=False), None),
        (compensation(max=None), None),
        (compensation(max=[]), None),
        (compensation(max={"amount": 10}), None),
        (compensation(currency=[]), None),
        (compensation(period={}), None),
        (None, None),
        ([], None),
        ("paid", None),
        (compensation(max=MAX_PLAUSIBLE_MONTHLY_INR), MAX_PLAUSIBLE_MONTHLY_INR),
        (
            compensation(max=MAX_PLAUSIBLE_HOURLY_INR, period="hour"),
            MAX_PLAUSIBLE_HOURLY_INR * PERIOD_TO_MONTH["hour"],
        ),
    ],
)
def test_monthly_equivalent_validation(pay, expected):
    result = monthly_inr_equivalent({"compensation": pay})
    assert result == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), 10**400])
def test_monthly_equivalent_nonfinite_max_falls_back_to_min(value):
    assert monthly_inr_equivalent({"compensation": compensation(max=value, min=50)}) == 50


@pytest.mark.parametrize("meta", [None, {}, [], "paid"])
def test_monthly_equivalent_missing_compensation(meta):
    assert monthly_inr_equivalent(meta) is None


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
def make_rows(db_session):
    token = uuid.uuid4().hex
    company = models.Company(slug=f"pay-sort-{token}", name=f"Pay Sort {token}")
    db_session.add(company)
    now = datetime.now(UTC)

    def make(compensations):
        rows = []
        for pay in compensations:
            suffix = uuid.uuid4().hex
            row = models.Opportunity(
                slug=f"pay-sort-{suffix}",
                title=f"paytest{token} Software Intern",
                title_normalized=f"paytest{token} software intern",
                category="internship",
                company=company,
                apply_url=f"https://example.com/pay-sort/{suffix}",
                status="active",
                primary_source="greenhouse",
                posted_at=now,
                first_seen_at=now,
                last_seen_at=now,
                deadline=now + timedelta(days=10),
                meta={} if pay is None else {"compensation": pay},
            )
            db_session.add(row)
            rows.append(row)
        db_session.flush()
        return rows

    return make, company, f"paytest{token}"


def test_sql_matches_python(db_session, make_rows):
    make, _company, _term = make_rows
    pays = [
        compensation(currency=currency, period=period, max=10)
        for currency in INR_PER_UNIT
        for period in PERIOD_TO_MONTH
    ] + [
        None,
        {"paid": True},
        compensation(unpaid=True),
        compensation(unpaid="80k"),
        compensation(unpaid=[]),
        compensation(unpaid={}),
        compensation(unpaid=1),
        compensation(currency="JPY"),
        compensation(period="week"),
        compensation(currency="USD", period="hour", max=800),
        compensation(currency="USD", period="hour", max=50),
        compensation(max="80k"),
        compensation(max="80k", min=40),
        compensation(max=None, min=40),
        compensation(max=-10, min=40),
        compensation(max=0, min=40),
        compensation(max=10**400, min=40),
        compensation(max=1e308),
        compensation(max=True, min=False),
        compensation(max=[], min={}),
        compensation(currency=[]),
        compensation(period={}),
        compensation(max=5_000_000),
        compensation(max=20_000_000),
        compensation(currency="USD", period="year", max=5_000_000),
        compensation(currency="USD", period="year", max=395_500),
        compensation(max=MAX_PLAUSIBLE_MONTHLY_INR),
        compensation(max=MAX_PLAUSIBLE_HOURLY_INR, period="hour"),
        [],
        "80k",
        100,
    ]
    rows = make(pays)
    actual = dict(
        db_session.execute(
            select(models.Opportunity.id, pay_rank_expression()).where(
                models.Opportunity.id.in_([row.id for row in rows])
            )
        ).all()
    )
    for row in rows:
        expected = monthly_inr_equivalent(row.meta)
        assert actual[row.id] == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize("endpoint", ["/feed", "/search"])
def test_pay_ordering_and_unusable_amounts(client, make_rows, endpoint):
    make, company, term = make_rows
    usable = make(
        [
            compensation(max=40_000),
            compensation(max=60_000, currency="USD", period="year"),
            compensation(max=50, currency="USD", period="hour"),
            compensation(max=2_000, currency="EUR"),
        ]
    )
    unusable = make(
        [
            None,
            {"paid": True},
            compensation(unpaid=True),
            compensation(currency="JPY"),
            compensation(period="week"),
            compensation(max=800, currency="USD", period="hour"),
            compensation(max="80k"),
        ]
    )
    params = {"sort": "pay", "company": company.slug, "limit": 100}
    if endpoint == "/search":
        params["q"] = term
    response = client.get(endpoint, params=params)
    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()["items"]]
    assert slugs[:4] == [usable[index].slug for index in [2, 1, 3, 0]]
    assert set(slugs[4:]) == {row.slug for row in unusable}


@pytest.mark.parametrize("sort", ["pay", "recent", "deadline"])
@pytest.mark.parametrize("endpoint", ["/feed", "/search"])
def test_students_toggle_precedes_sort_keys(client, db_session, make_rows, sort, endpoint):
    make, company, term = make_rows
    intern, senior = make([compensation(max=10_000), compensation(max=100_000)])
    senior.title = f"{term} Senior Software Engineer"
    senior.title_normalized = senior.title.lower()
    senior.category = "job"
    senior.posted_at += timedelta(days=1)
    senior.deadline -= timedelta(days=1)
    db_session.flush()
    params = {"sort": sort, "company": company.slug}
    if endpoint == "/search":
        params["q"] = term
    for students, expected in [
        (None, [senior, intern]),
        ("false", [senior, intern]),
        ("true", [intern, senior]),
    ]:
        query = params if students is None else {**params, "students": students}
        response = client.get(endpoint, params=query)
        assert response.status_code == 200
        assert [item["slug"] for item in response.json()["items"]] == [row.slug for row in expected]


@pytest.mark.parametrize("endpoint", ["/feed", "/search"])
def test_students_pay_keeps_undisclosed_internships_last(client, db_session, make_rows, endpoint):
    make, company, term = make_rows
    intern, senior = make([compensation(max=10_000), compensation(max=800_000)])
    undisclosed = make([None, {"paid": True}, compensation(unpaid=True)])
    senior.title = f"{term} Senior Software Engineer"
    senior.title_normalized = senior.title.lower()
    senior.category = "job"
    db_session.flush()

    params = {"sort": "pay", "students": "true", "company": company.slug}
    if endpoint == "/search":
        params["q"] = term
    response = client.get(endpoint, params=params)
    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()["items"]]
    assert slugs[:2] == [intern.slug, senior.slug]
    assert set(slugs[2:]) == {row.slug for row in undisclosed}


@pytest.mark.parametrize("endpoint", ["/feed", "/search"])
def test_students_deadline_keeps_undated_internships_last(client, db_session, make_rows, endpoint):
    make, company, term = make_rows
    intern, job, undated = make([None, None, None])
    job.title = f"{term} Software Engineer"
    job.title_normalized = job.title.lower()
    job.category = "job"
    job.deadline = datetime.now(UTC) + timedelta(days=1)
    undated.deadline = None
    db_session.flush()

    params = {"sort": "deadline", "students": "true", "company": company.slug}
    if endpoint == "/search":
        params["q"] = term
    response = client.get(endpoint, params=params)
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["items"]] == [
        intern.slug,
        job.slug,
        undated.slug,
    ]


def test_default_feed_and_legacy_student_ignore_students(client, db_session, make_rows):
    make, company, _term = make_rows
    intern, job = make([compensation(max=10), compensation(max=100)])
    job.category = "job"
    job.last_seen_at += timedelta(days=1)
    db_session.flush()
    expected = [intern.slug, job.slug]
    for extra in [{}, {"sort": "student"}, {"sort": "student", "students": "false"}]:
        response = client.get("/feed", params={"company": company.slug, **extra})
        assert response.status_code == 200
        assert [item["slug"] for item in response.json()["items"]] == expected


def test_closed_pay_rows_stay_last(client, db_session, make_rows, monkeypatch):
    make, company, _term = make_rows
    opened, closed = make([compensation(max=100), compensation(max=1_000_000)])
    closed.closed_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.flush()
    params = {"sort": "pay", "company": company.slug}
    # Normal browse excludes closed rows. Admit both here to exercise its leading key.
    assert [item["slug"] for item in client.get("/feed", params=params).json()["items"]] == [
        opened.slug
    ]
    monkeypatch.setattr(feed, "exclude_closed_now", true)
    response = client.get("/feed", params={**params, "students": "true"})
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["items"]] == [opened.slug, closed.slug]
