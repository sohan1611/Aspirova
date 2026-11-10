"""Integration tests for the authenticated bookmarks tracker endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.bookmarks import enforce_bookmark_write_limit
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


def test_patch_moves_bookmark_through_stages(client, db_session, seeded) -> None:
    opportunity = seeded["opportunity"]
    client.post(f"/bookmarks/{opportunity.slug}")

    for status in ("applied", "interviewing"):
        response = client.patch(f"/bookmarks/{opportunity.slug}", json={"status": status})

        assert response.status_code == 204
        bookmark = db_session.get(models.Bookmark, (seeded["user"].id, opportunity.id))
        assert bookmark is not None
        assert bookmark.status == status

    listed = client.get("/bookmarks")
    assert listed.json()[0]["bookmark_status"] == "interviewing"


def test_patch_non_bookmarked_opportunity_returns_404(client, seeded) -> None:
    response = client.patch(
        f"/bookmarks/{seeded['other_opportunity'].slug}", json={"status": "applied"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Bookmark not found"


def test_patch_invalid_bookmark_status_returns_422(client, seeded) -> None:
    opportunity = seeded["opportunity"]
    client.post(f"/bookmarks/{opportunity.slug}")

    response = client.patch(f"/bookmarks/{opportunity.slug}", json={"status": "rejected"})

    assert response.status_code == 422


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
