"""Integration tests for the signed-out-friendly bug-report endpoint."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import reports
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
def client(db_session: Session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _report_for_message(db_session: Session, message: str) -> models.BugReport | None:
    return db_session.scalar(select(models.BugReport).where(models.BugReport.message == message))


def test_valid_report_is_stored_and_returns_ok(client, db_session, monkeypatch) -> None:
    monkeypatch.setattr(reports.get_settings(), "waitlist_notify_email", "")
    message = f"The link redirects to an expired listing ({uuid.uuid4()})."

    response = client.post(
        "/reports",
        json={"category": "dead_link", "message": message, "page_url": "https://example.com"},
        headers={"X-Forwarded-For": "198.51.100.41"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    report = _report_for_message(db_session, message)
    assert report is not None
    assert report.category == "dead_link"
    assert report.message == message
    assert report.opportunity_id is None


def test_unknown_opportunity_slug_stores_an_unlinked_report(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(reports.get_settings(), "waitlist_notify_email", "")
    message = f"Unknown opportunity slug test ({uuid.uuid4()})."

    response = client.post(
        "/reports",
        json={
            "category": "wrong_info",
            "message": message,
            "opportunity_slug": f"missing-{uuid.uuid4()}",
        },
        headers={"X-Forwarded-For": "198.51.100.42"},
    )

    assert response.status_code == 200
    report = _report_for_message(db_session, message)
    assert report is not None
    assert report.opportunity_id is None


def test_invalid_category_returns_422(client) -> None:
    response = client.post(
        "/reports",
        json={"category": "not-a-category", "message": "This should be rejected."},
        headers={"X-Forwarded-For": "198.51.100.43"},
    )

    assert response.status_code == 422


def test_blank_message_returns_422(client) -> None:
    response = client.post(
        "/reports",
        json={"category": "bug", "message": "   "},
        headers={"X-Forwarded-For": "198.51.100.44"},
    )

    assert response.status_code == 422


def test_known_opportunity_slug_links_the_report(client, db_session, monkeypatch) -> None:
    monkeypatch.setattr(reports.get_settings(), "waitlist_notify_email", "")
    suffix = uuid.uuid4()
    opportunity = models.Opportunity(
        slug=f"report-opportunity-{suffix}",
        title="Reportable opportunity",
        apply_url="https://example.com/apply",
    )
    db_session.add(opportunity)
    db_session.flush()
    message = f"The deadline is wrong ({suffix})."

    response = client.post(
        "/reports",
        json={
            "category": "wrong_info",
            "message": message,
            "opportunity_slug": opportunity.slug,
        },
        headers={"X-Forwarded-For": "198.51.100.45"},
    )

    assert response.status_code == 200
    report = _report_for_message(db_session, message)
    assert report is not None
    assert report.opportunity_id == opportunity.id
