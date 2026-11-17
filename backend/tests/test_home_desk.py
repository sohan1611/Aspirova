"""DISC-02 integration tests; run only against the reviewer's throwaway Postgres."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from api import home, middleware
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models

NOW = datetime.now(timezone.utc)


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
def reader(db_session):
    user = models.User(email=f"desk-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def client(db_session, reader, monkeypatch):
    monkeypatch.setattr(home, "get_redis", lambda: None)
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: reader
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def role(db, **changes):
    values = dict(
        slug=f"desk-role-{uuid.uuid4()}",
        title="Software internship",
        category="internship",
        status="active",
        apply_url="https://boards.greenhouse.io/example/jobs/1",
        first_seen_at=NOW - timedelta(hours=1),
        last_seen_at=NOW,
        deadline=NOW + timedelta(days=7),
        deadline_confidence="explicit",
    )
    item = models.Opportunity(**(values | changes))
    db.add(item)
    db.flush()
    return item


def bookmark(db, user, item, **changes):
    db.add(models.Bookmark(user_id=user.id, opportunity_id=item.id, **changes))
    db.flush()


def watch(db, user, *, status="announced", days=2, **changes):
    programme = models.Programme(
        slug=f"desk-programme-{uuid.uuid4()}",
        name="Review programme",
        organiser="Example",
        category="early_career",
        url="https://example.com/programme",
        editions=[
            models.ProgrammeEdition(
                year=NOW.year,
                status=status,
                opens_at=NOW + timedelta(days=1),
                closes_at=NOW + timedelta(days=days),
                **changes,
            )
        ],
    )
    db.add(programme)
    db.flush()
    db.add(models.ProgrammeWatch(user_id=user.id, programme_id=programme.id))
    db.flush()
    return programme


def test_signed_out_is_401(client):
    app.dependency_overrides.pop(get_current_user)
    response = client.get("/home/desk")
    assert response.status_code == 401


def test_empty_shape_and_no_store(client):
    response = client.get("/home/desk")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"matches", "deadlines", "followed", "applications", "warnings"}
    for block in body.values():
        assert block["items"] == []
        assert block["count"] == 0
        assert block["reason"]
    assert body["matches"]["reason"] == "no_profile"


def test_personal_blocks_are_user_scoped(client, db_session, reader):
    other = models.User(email=f"other-desk-{uuid.uuid4()}@example.com")
    company = models.Company(slug=f"desk-co-{uuid.uuid4()}", name="Private follow")
    db_session.add_all([other, company])
    db_session.flush()
    item = role(db_session, company=company, status="withdrawn")
    bookmark(db_session, other, item, status="applied", note="Private note")
    watch(db_session, other)
    db_session.add(models.DreamCompany(user_id=other.id, company_id=company.id))
    db_session.flush()
    body = client.get("/home/desk").json()
    assert all(block["items"] == [] for block in body.values())
    assert "Private note" not in str(body)
    # Another user's bookmark never suppresses this reader's new matches.
    reader.skills = [{"name": f"desk-skill-{uuid.uuid4()}", "level": "beginner"}]
    item.status = "active"
    item.skills = [reader.skills[0]["name"]]
    db_session.flush()
    assert client.get("/home/desk").json()["matches"]["items"][0]["slug"] == item.slug


def test_deadlines_only_explicit_open_listings_and_official_days(client, db_session, reader):
    accepted = role(db_session, deadline=NOW + timedelta(days=3))
    bookmark(db_session, reader, accepted)
    for values in (
        {"deadline_confidence": "estimated"},
        {"deadline_confidence": "unknown"},
        {"deadline": None},
        {"deadline": NOW - timedelta(days=1)},
        {"closed_at": NOW},
        {"status": "withdrawn"},
        {"is_hidden": True},
    ):
        bookmark(db_session, reader, role(db_session, **values))
    official = watch(db_session, reader)
    watch(db_session, reader, status="expected")
    watch(db_session, reader, status="closed")
    response = client.get("/home/desk").json()["deadlines"]
    assert [item["slug"] for item in response["items"]] == [official.slug, accepted.slug]
    assert all(item["confidence"] == "explicit" for item in response["items"])


def test_applications_follow_next_up_order_and_preserve_safety(client, db_session, reader):
    stages = [
        "saved",
        "planned",
        "applied",
        "assessment",
        "interviewing",
        "offer",
        "rejected",
        "archived",
    ]
    slugs = {}
    for stage in stages:
        item = role(db_session, deadline=NOW + timedelta(days=10))
        if stage == "interviewing":
            item.status = "withdrawn"
            item.meta = {"safety": {"kind": "scam", "note": "Avoid", "flagged_at": NOW.isoformat()}}
        if stage == "applied":
            item.closed_at = NOW
        bookmark(
            db_session,
            reader,
            item,
            status=stage,
            status_date=(NOW + timedelta(days=1 if stage == "assessment" else 2)).date(),
        )
        slugs[stage] = item.slug
    body = client.get("/home/desk").json()
    assert body["applications"]["count"] == 4
    assert [item["slug"] for item in body["applications"]["items"]][:2] == [
        slugs["assessment"],
        slugs["interviewing"],
    ]
    assert len(body["applications"]["items"]) == 3
    warning_items = {item["slug"]: item for item in body["warnings"]["items"]}
    assert set(warning_items) == {slugs["applied"], slugs["interviewing"]}
    assert warning_items[slugs["interviewing"]]["safety"]["kind"] == "scam"
    assert warning_items[slugs["applied"]]["destination"]["kind"] == "ats"


def test_matches_reuse_for_you_skill_precedence_and_exclude_saved_old_closed(
    client, db_session, reader
):
    skill_a, skill_b = f"DeskA{uuid.uuid4()}", f"DeskB{uuid.uuid4()}"
    reader.skills = [{"name": skill_a}, {"name": skill_b}]
    stronger = role(db_session, skills=[skill_a, skill_b], last_seen_at=NOW - timedelta(days=1))
    weaker = role(db_session, skills=[skill_a])
    saved = role(db_session, skills=[skill_a, skill_b])
    bookmark(db_session, reader, saved)
    role(db_session, skills=[skill_a], first_seen_at=NOW - timedelta(days=15))
    role(db_session, skills=[skill_a], closed_at=NOW)
    role(db_session, skills=[skill_a], category="competition")
    db_session.flush()
    items = client.get("/home/desk").json()["matches"]["items"]
    assert [item["slug"] for item in items] == [stronger.slug, weaker.slug]
    ranked = client.get("/for-you", params={"skills": f"{skill_a},{skill_b}"}).json()["items"]
    assert [item["slug"] for item in ranked if item["slug"] in {stronger.slug, weaker.slug}] == [
        stronger.slug,
        weaker.slug,
    ]


def test_profile_terms_use_shared_expansion(client, db_session, reader, monkeypatch):
    term = "deskterm" + uuid.uuid4().hex
    monkeypatch.setattr(home, "build_feed_terms", lambda profile, skills: [term])
    reader.field_profile = {"stream": "test", "interests": [term]}
    match = role(db_session, title=f"{term} {term}")
    assert client.get("/home/desk").json()["matches"]["items"][0]["slug"] == match.slug


def test_public_closing_rail_filters_explicit_before_limit(client, db_session):
    company = models.Company(slug=f"desk-closing-{uuid.uuid4()}", name="Deadline test")
    db_session.add(company)
    db_session.flush()
    for confidence in ("estimated", "unknown"):
        role(db_session, company=company, deadline_confidence=confidence)
    role(db_session, company=company, closed_at=NOW)
    accepted = [
        role(db_session, company=company, deadline=NOW + timedelta(days=index + 2))
        for index in range(8)
    ]
    response = client.get(
        "/feed",
        params={
            "company": company.slug,
            "deadline_confidence": "explicit",
            "sort": "deadline",
            "limit": 6,
        },
    )
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["items"]] == [
        item.slug for item in accepted[:6]
    ]


def test_query_count_constant_with_many_distinct_companies_and_watches(db_session, reader):
    reader.skills = [{"name": f"DeskCount{uuid.uuid4()}"}]
    db_session.flush()
    # Snapshot auth fields before expiring ORM rows; auth's single user lookup
    # is outside this selector budget and independent of tracked item count.
    user = SimpleNamespace(id=reader.id, skills=reader.skills, field_profile=None)

    def seed():
        company = models.Company(slug=f"desk-count-co-{uuid.uuid4()}", name="Count test")
        db_session.add(company)
        db_session.flush()
        db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
        bookmark(db_session, user, role(db_session, company=company), status="planned")
        role(db_session, company=company, skills=[user.skills[0]["name"]])
        watch(db_session, user)

    def counted():
        db_session.expire_all()
        statements = []

        def count(*args):
            statements.append(args[2])

        event.listen(db_session.bind, "before_cursor_execute", count)
        try:
            result = home.build_home_desk(db_session, user, now=NOW)
            assert result.followed.items and result.matches.items
        finally:
            event.remove(db_session.bind, "before_cursor_execute", count)
        return len(statements)

    seed()
    one = counted()
    for _ in range(12):
        seed()
    assert counted() == one == 4


def test_per_user_read_limit(monkeypatch):
    # Dependency-only: does not need a DB or a real Redis connection.
    limiter = AsyncMock(return_value=SimpleNamespace(allowed=False, retry_after_seconds=12))
    monkeypatch.setattr(home, "check_rate_limit", limiter)
    monkeypatch.setattr(home, "get_redis", lambda: None)
    user = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(home.enforce_home_desk_limit(user))
    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "12"}
    assert limiter.call_args.kwargs["identifier"] == str(user.id)
