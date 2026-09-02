import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
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
def programme_rows(db_session: Session):
    suffix = uuid.uuid4().hex
    token = f"programme-filter-{suffix}"
    research_tag = f"{token}-research"
    policy_tag = f"{token}-policy"

    def make_programme(
        *,
        slug: str,
        name: str,
        organiser: str,
        category: str,
        status: str,
        tags: list[str],
    ) -> models.Programme:
        programme = models.Programme(
            slug=f"{slug}-{suffix}",
            name=f"{token} {name}",
            organiser=organiser,
            category=category,
            url=f"https://example.com/programme-filter/{slug}/{suffix}",
            description=f"{token} fixture",
            tags=tags,
            country="IN",
            is_active=True,
        )
        db_session.add(programme)
        db_session.flush()
        db_session.add(
            models.ProgrammeEdition(
                programme_id=programme.id,
                year=2030,
                status=status,
            )
        )
        db_session.flush()
        return programme

    iit = make_programme(
        slug="programme-filter-iit",
        name="IIT research",
        organiser=(f"Indian Institute of Technology (IIT), Filter Campus {suffix}"),
        category="research_internship",
        status="expected",
        tags=[research_tag],
    )
    company = make_programme(
        slug="programme-filter-company",
        name="Company research",
        organiser=f"Filter Labs Pvt Ltd {suffix}",
        category="fellowship",
        status="announced",
        tags=[research_tag, policy_tag],
    )
    open_source = make_programme(
        slug="programme-filter-open-source",
        name="Open source",
        organiser=f"Open Source Foundation {suffix}",
        category="open_source",
        status="open",
        tags=[policy_tag],
    )

    return {
        "token": token,
        "research_tag": research_tag,
        "policy_tag": policy_tag,
        "iit": iit,
        "company": company,
        "open_source": open_source,
    }


def _slugs(body: dict) -> set[str]:
    return {item["slug"] for item in body["items"]}


def _facet_by_value(options: list[dict], value: str) -> dict | None:
    return next((option for option in options if option["value"] == value), None)


def test_programme_filters_accept_repeated_values_as_or(
    client: TestClient,
    programme_rows,
) -> None:
    body = client.get(
        "/programmes",
        params=[
            ("q", programme_rows["token"]),
            ("category", "research_internship"),
            ("category", "fellowship"),
            ("status", "expected"),
            ("status", "announced"),
            ("field", programme_rows["research_tag"]),
            ("limit", "20"),
        ],
    ).json()

    assert body["total"] == 2
    assert _slugs(body) == {
        programme_rows["iit"].slug,
        programme_rows["company"].slug,
    }


def test_programme_organiser_exact_match_and_institution_type_are_anded(
    client: TestClient,
    programme_rows,
) -> None:
    body = client.get(
        "/programmes",
        params=[
            ("q", programme_rows["token"]),
            ("organiser", programme_rows["iit"].organiser),
            ("organiser", programme_rows["company"].organiser),
            ("institution_type", "iit"),
            ("limit", "20"),
        ],
    ).json()

    assert body["total"] == 1
    assert _slugs(body) == {programme_rows["iit"].slug}


def test_programme_facets_return_counted_programme_options(
    client: TestClient,
    programme_rows,
) -> None:
    body = client.get(
        "/facets",
        params=[
            ("source", "programmes"),
            ("category", "research_internship"),
            ("category", "fellowship"),
        ],
    ).json()

    field = _facet_by_value(body["programme_fields"], programme_rows["research_tag"])
    organiser = _facet_by_value(
        body["programme_organisers"],
        programme_rows["iit"].organiser,
    )
    iit = _facet_by_value(body["programme_institution_types"], "iit")
    expected = _facet_by_value(body["programme_statuses"], "expected")
    announced = _facet_by_value(body["programme_statuses"], "announced")

    assert field is not None
    assert field["count"] == 2
    assert organiser is not None
    assert organiser["count"] == 1
    assert iit is not None
    assert iit["count"] >= 1
    assert expected is not None
    assert expected["count"] >= 1
    assert announced is not None
    assert announced["count"] >= 1
