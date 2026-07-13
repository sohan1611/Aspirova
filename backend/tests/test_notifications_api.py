"""Integration tests for the authenticated in-app notification endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
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
def seeded(db_session: Session):
    suffix = str(uuid.uuid4())
    user = models.User(email=f"notifications-user-{suffix}@example.com")
    other_user = models.User(email=f"notifications-other-user-{suffix}@example.com")
    company = models.Company(
        slug=f"notifications-company-{suffix}",
        name="Dream Company",
    )
    opportunity = models.Opportunity(
        slug=f"notifications-opportunity-{suffix}",
        company=company,
        title="Software Engineering Intern",
        apply_url="https://example.com/apply",
    )
    db_session.add_all([user, other_user, company, opportunity])
    db_session.flush()

    sent_at = datetime.now(timezone.utc)
    notifications = [
        models.Notification(
            user_id=user.id,
            type="closing_soon",
            opportunity_id=opportunity.id,
            status="sent",
            sent_at=sent_at,
        ),
        models.Notification(
            user_id=user.id,
            type="instant_alert",
            opportunity_id=opportunity.id,
            status="sent",
            sent_at=sent_at + timedelta(seconds=1),
        ),
        models.Notification(
            user_id=user.id,
            type="daily_digest",
            status="sent",
            sent_at=sent_at + timedelta(seconds=2),
        ),
        models.Notification(
            user_id=user.id,
            type="weekly_report",
            status="sent",
            sent_at=sent_at + timedelta(seconds=3),
        ),
        models.Notification(
            user_id=user.id,
            type="instant_alert",
            opportunity_id=opportunity.id,
            status="failed",
        ),
        models.Notification(
            user_id=other_user.id,
            type="instant_alert",
            opportunity_id=opportunity.id,
            status="sent",
            sent_at=sent_at + timedelta(seconds=4),
        ),
    ]
    db_session.add_all(notifications)
    db_session.flush()
    return {
        "user": user,
        "other_user": other_user,
        "notifications": notifications,
        "opportunity": opportunity,
    }


@pytest.fixture
def client(db_session: Session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_list_notifications_returns_delivered_alerts_with_client_ready_copy(client, seeded) -> None:
    response = client.get("/notifications")

    assert response.status_code == 200
    payload = response.json()
    assert payload["unread"] == 4
    assert len(payload["items"]) == 4
    assert all(item["read"] is False for item in payload["items"])
    assert all(item["id"] != seeded["notifications"][-1].id for item in payload["items"])

    items_by_type = {item["type"]: item for item in payload["items"]}
    closing_soon = items_by_type["closing_soon"]
    assert closing_soon["id"] == seeded["notifications"][0].id
    assert closing_soon["title"] == "Closing soon"
    assert closing_soon["body"] == "‘Software Engineering Intern’ closes soon — don’t miss it."
    assert closing_soon["opportunity_slug"] == seeded["opportunity"].slug
    assert closing_soon["opportunity_title"] == "Software Engineering Intern"
    assert closing_soon["company_name"] == "Dream Company"
    assert closing_soon["created_at"]
    assert items_by_type["instant_alert"]["title"] == "New at a dream company"
    assert (
        items_by_type["instant_alert"]["body"]
        == "‘Software Engineering Intern’ just opened at Dream Company."
    )
    assert items_by_type["daily_digest"]["title"] == "Your daily digest"
    assert (
        items_by_type["daily_digest"]["body"] == "New opportunities matched your interests today."
    )
    assert items_by_type["weekly_report"]["title"] == "Your weekly career report"
    assert items_by_type["weekly_report"]["body"] == "Your week in opportunities is ready."


def test_unread_count_and_mark_all_read_are_scoped_to_current_user(
    client, db_session, seeded
) -> None:
    response = client.get("/notifications/unread-count")
    assert response.status_code == 200
    assert response.json() == {"unread": 4}

    marked = client.post("/notifications/read")
    assert marked.status_code == 200
    assert marked.json() == {"unread": 0}
    assert client.get("/notifications/unread-count").json() == {"unread": 0}

    user_notifications = list(
        db_session.scalars(
            select(models.Notification).where(models.Notification.user_id == seeded["user"].id)
        )
    )
    assert all(notification.read_at is not None for notification in user_notifications)

    other_notification = seeded["notifications"][-1]
    assert other_notification.read_at is None


def test_other_users_notifications_are_not_visible(client, seeded) -> None:
    response = client.get("/notifications")

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()["items"]}
    assert seeded["notifications"][-1].id not in returned_ids


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/notifications"),
        ("get", "/notifications/unread-count"),
        ("post", "/notifications/read"),
    ],
)
def test_notification_endpoints_require_authentication(method: str, path: str) -> None:
    client = TestClient(app)

    response = getattr(client, method)(path)

    assert response.status_code == 401
