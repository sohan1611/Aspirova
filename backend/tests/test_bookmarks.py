"""Integration tests for the authenticated bookmarks tracker endpoints."""

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.bookmarks import enforce_bookmark_write_limit
from api import bookmarks
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
    user = models.User(email=f"bookmark-test-{suffix}@example.com")
    opportunity = models.Opportunity(
        slug=f"bookmark-test-opportunity-{suffix}",
        title="Bookmark test opportunity",
        apply_url="https://example.com/bookmark-test",
    )
    other_opportunity = models.Opportunity(
        slug=f"bookmark-test-other-opportunity-{suffix}",
        title="Other bookmark test opportunity",
        apply_url="https://example.com/bookmark-test-other",
    )
    db_session.add_all([user, opportunity, other_opportunity])
    db_session.flush()
    return {
        "user": user,
        "opportunity": opportunity,
        "other_opportunity": other_opportunity,
    }


@pytest.fixture
def client(db_session: Session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    app.dependency_overrides[enforce_bookmark_write_limit] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(enforce_bookmark_write_limit, None)


def test_new_bookmark_defaults_to_saved_and_list_returns_status(client, db_session, seeded) -> None:
    opportunity = seeded["opportunity"]

    response = client.post(f"/bookmarks/{opportunity.slug}")

    assert response.status_code == 204
    bookmark = db_session.get(models.Bookmark, (seeded["user"].id, opportunity.id))
    assert bookmark is not None
    assert bookmark.status == "saved"

    listed = client.get("/bookmarks")

    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["slug"] == opportunity.slug
    assert items[0]["bookmark_status"] == "saved"
    assert items[0]["note"] is None
    assert items[0]["status_date"] is None
    assert items[0]["status_changed_at"] is None


def test_patch_moves_bookmark_through_stages(client, db_session, seeded) -> None:
    opportunity = seeded["opportunity"]
    client.post(f"/bookmarks/{opportunity.slug}")

    for status in (
        "planned",
        "applied",
        "assessment",
        "interviewing",
        "offer",
        "rejected",
        "archived",
        "saved",
    ):
        response = client.patch(f"/bookmarks/{opportunity.slug}", json={"status": status})

        assert response.status_code == 204
        bookmark = db_session.get(models.Bookmark, (seeded["user"].id, opportunity.id))
        assert bookmark is not None
        assert bookmark.status == status

    listed = client.get("/bookmarks")
    assert listed.json()[0]["bookmark_status"] == "saved"


def test_patch_non_bookmarked_opportunity_returns_404(client, seeded) -> None:
    response = client.patch(
        f"/bookmarks/{seeded['other_opportunity'].slug}", json={"status": "applied"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Bookmark not found"


@pytest.mark.parametrize("status", ["unknown", "Interview", "", None, 4])
def test_patch_invalid_bookmark_status_returns_422(client, seeded, status) -> None:
    opportunity = seeded["opportunity"]
    client.post(f"/bookmarks/{opportunity.slug}")

    response = client.patch(f"/bookmarks/{opportunity.slug}", json={"status": status})

    assert response.status_code == 422


def test_patch_optional_fields_and_real_status_change_only(client, db_session, seeded, monkeypatch):
    path = f"/bookmarks/{seeded['opportunity'].slug}"
    client.post(path)
    key = (seeded["user"].id, seeded["opportunity"].id)
    assert db_session.get(models.Bookmark, key).status_changed_at is None
    assert (
        client.patch(
            path, json={"note": "Bring portfolio", "status_date": "2026-11-21"}
        ).status_code
        == 204
    )
    bookmark = db_session.get(models.Bookmark, key)
    assert bookmark.status == "saved"
    assert bookmark.note == "Bring portfolio"
    assert bookmark.status_date == date(2026, 11, 21)
    assert bookmark.status_changed_at is None

    first = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    clock = Mock()
    clock.now.return_value = first
    monkeypatch.setattr(bookmarks, "datetime", clock)
    assert client.patch(path, json={"status": "interviewing"}).status_code == 204
    db_session.expire_all()
    assert db_session.get(models.Bookmark, key).status_changed_at == first
    second = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    clock.now.return_value = second
    for payload in (
        {},
        {"status": "interviewing"},
        {"note": "Updated"},
        {"status_date": "2026-11-22"},
    ):
        assert client.patch(path, json=payload).status_code == 204
        db_session.expire_all()
        assert db_session.get(models.Bookmark, key).status_changed_at == first
    assert client.patch(path, json={"note": None, "status_date": None}).status_code == 204
    row = client.get("/bookmarks").json()[0]
    assert row["note"] is None and row["status_date"] is None
    assert row["bookmark_status"] == "interviewing"
    assert client.patch(path, json={"status": "offer"}).status_code == 204
    db_session.expire_all()
    assert db_session.get(models.Bookmark, key).status_changed_at == second
    assert clock.now.call_count == 2


@pytest.mark.parametrize("length,expected", [(0, 204), (1000, 204), (1001, 422)])
def test_note_length(client, seeded, length, expected):
    path = f"/bookmarks/{seeded['opportunity'].slug}"
    client.post(path)
    assert client.patch(path, json={"note": "x" * length}).status_code == expected
    if expected == 204:
        assert client.get("/bookmarks").json()[0]["note"] == "x" * length


@pytest.mark.parametrize(
    "value", ["2026-02-29", "2026-13-01", "21 Nov", "2026-11-21T00:00:00Z", "20261121", "", 0, True]
)
def test_status_date_rejects_invalid_calendar_dates(client, seeded, value):
    path = f"/bookmarks/{seeded['opportunity'].slug}"
    client.post(path)
    assert client.patch(path, json={"status_date": value}).status_code == 422


def test_date_round_trip_and_invalid_field_types(client, seeded):
    path = f"/bookmarks/{seeded['opportunity'].slug}"
    client.post(path)
    assert client.patch(path, json={"status_date": "2028-02-29"}).status_code == 204
    assert client.get("/bookmarks").json()[0]["status_date"] == "2028-02-29"
    for payload in ({"note": 123}, {"status_changed_at": "2026-11-17T00:00:00Z"}):
        assert client.patch(path, json=payload).status_code == 422


@pytest.mark.parametrize("state", ["active", "closed", "withdrawn", "scam"])
def test_get_action_center_shape(client, db_session, seeded, state):
    opportunity = seeded["opportunity"]
    opportunity.apply_url = "https://boards.greenhouse.io/example/jobs/1"
    opportunity.deadline = datetime(2026, 11, 21, tzinfo=timezone.utc)
    opportunity.status = "withdrawn" if state == "scam" else state
    opportunity.closed_at = (
        datetime(2026, 11, 16, tzinfo=timezone.utc) if state != "active" else None
    )
    if state in {"withdrawn", "scam"}:
        opportunity.meta = {
            "safety": {
                "kind": "scam" if state == "scam" else "recalled",
                "note": "Founder warning",
                "source_url": "https://example.com/warning",
                "flagged_at": "2026-11-16T00:00:00Z",
            }
        }
    client.post(f"/bookmarks/{opportunity.slug}")
    client.patch(
        f"/bookmarks/{opportunity.slug}",
        json={"status": "assessment", "note": "Prepare", "status_date": "2026-11-20"},
    )
    row = client.get("/bookmarks").json()[0]
    assert row["bookmark_status"] == "assessment"
    assert row["status"] == opportunity.status
    assert bool(row["closed_at"]) == (state != "active")
    assert row["deadline"].startswith("2026-11-21")
    assert row["note"] == "Prepare" and row["status_date"] == "2026-11-20"
    assert row["status_changed_at"] is not None
    assert row["apply_url"] == opportunity.apply_url
    assert row["destination"] == {
        "kind": "ats",
        "host": "boards.greenhouse.io",
        "label": "Greenhouse",
    }
    if state in {"withdrawn", "scam"}:
        assert row["safety"]["kind"] == row["meta"]["safety"]["kind"]
    else:
        assert row["safety"] is None


def test_get_query_count_is_constant_for_one_and_ten_bookmarks(db_session, seeded):
    user_id = seeded["user"].id
    db_session.add(models.Bookmark(user_id=user_id, opportunity_id=seeded["opportunity"].id))
    db_session.flush()

    def counted_list(expected):
        db_session.expire_all()
        statements = []

        def count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db_session.bind, "before_cursor_execute", count)
        try:
            rows = bookmarks.list_bookmarks(db_session, SimpleNamespace(id=user_id))
            assert len(rows) == expected
            assert all(row.destination.kind == "unverified" for row in rows)
        finally:
            event.remove(db_session.bind, "before_cursor_execute", count)
        return len(statements)

    one_count = counted_list(1)
    for _ in range(9):
        # Company domains are unique (ix_companies_domain_unique).
        company = models.Company(
            slug=f"bookmark-company-{uuid.uuid4()}",
            name="Test company",
            domain=f"bookmark-{uuid.uuid4().hex[:12]}.example.com",
        )
        opportunity = models.Opportunity(
            slug=f"bookmark-count-{uuid.uuid4()}",
            title="Count test",
            apply_url="https://boards.greenhouse.io/test",
            company=company,
        )
        db_session.add(opportunity)
        db_session.flush()
        db_session.add(models.Bookmark(user_id=user_id, opportunity_id=opportunity.id))
    db_session.flush()
    # Destination kinds vary with company/domain; reading them must still stay in one query.
    db_session.expire_all()
    statements = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", count)
    try:
        rows = bookmarks.list_bookmarks(db_session, SimpleNamespace(id=user_id))
        assert len(rows) == 10
        assert sum(row.destination.kind == "ats" for row in rows) == 9
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count)
    assert len(statements) == one_count == 1


def test_action_center_fields_are_scoped_to_current_user(client, db_session, seeded):
    other_user = models.User(email=f"bookmark-owner-{uuid.uuid4()}@example.com")
    db_session.add(other_user)
    db_session.flush()
    db_session.add(
        models.Bookmark(
            user_id=other_user.id,
            opportunity_id=seeded["opportunity"].id,
            note="Private note",
            status_date=date(2026, 11, 21),
        )
    )
    db_session.flush()
    assert client.get("/bookmarks").json() == []
    assert (
        client.patch(
            f"/bookmarks/{seeded['opportunity'].slug}", json={"note": "Overwrite"}
        ).status_code
        == 404
    )


def test_repeated_save_preserves_one_bookmark_and_its_stage(client, db_session, seeded) -> None:
    opportunity = seeded["opportunity"]
    assert client.post(f"/bookmarks/{opportunity.slug}").status_code == 204
    assert (
        client.patch(f"/bookmarks/{opportunity.slug}", json={"status": "interviewing"}).status_code
        == 204
    )
    for _ in range(3):
        assert client.post(f"/bookmarks/{opportunity.slug}").status_code == 204
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(models.Bookmark)
            .where(
                models.Bookmark.user_id == seeded["user"].id,
                models.Bookmark.opportunity_id == opportunity.id,
            )
        )
        == 1
    )
    db_session.expire_all()
    assert (
        db_session.get(models.Bookmark, (seeded["user"].id, opportunity.id)).status
        == "interviewing"
    )


def test_delete_retries_and_unknown_opportunity_succeed(client, seeded) -> None:
    path = f"/bookmarks/{seeded['opportunity'].slug}"
    assert client.post(path).status_code == 204
    assert client.delete(path).status_code == 204
    assert client.delete(path).status_code == 204
    assert client.delete(f"/bookmarks/missing-{uuid.uuid4()}").status_code == 204


def test_undo_can_restore_application_stage(client, seeded) -> None:
    path = f"/bookmarks/{seeded['opportunity'].slug}"
    assert client.post(path).status_code == 204
    assert client.patch(path, json={"status": "offer"}).status_code == 204
    assert client.delete(path).status_code == 204
    assert client.post(path).status_code == 204
    assert client.patch(path, json={"status": "offer"}).status_code == 204
    assert client.get("/bookmarks").json()[0]["bookmark_status"] == "offer"
