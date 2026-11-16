"""Watch API, privacy/export and FK lifecycle integration tests.

These use the suite's shared engine and the existing outer-transaction
fixture pattern; the runner must supply a disposable, migrated database.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.account import enforce_account_export_limit
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from api.programme_watches import enforce_programme_watch_write_limit
from core import models
from core.programme_watches import programme_signature


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


def _programme(index: int = 0) -> models.Programme:
    return models.Programme(
        slug=f"watch-api-{index}-{uuid.uuid4().hex}",
        name=f"Watch programme {index}",
        organiser="Watch organiser",
        category="fellowship",
        url="https://example.com/programme",
    )


@pytest.fixture
def seeded(db_session):
    user = models.User(email=f"watch-api-{uuid.uuid4()}@example.com")
    other = models.User(email=f"watch-api-other-{uuid.uuid4()}@example.com")
    programme = _programme()
    now = datetime.now(timezone.utc)
    programme.editions = [
        models.ProgrammeEdition(
            year=now.year,
            status="expected",
            opens_at=now + timedelta(days=30),
            closes_at=now + timedelta(days=60),
        )
    ]
    db_session.add_all([user, other, programme])
    db_session.flush()
    return {"user": user, "other": other, "programme": programme}


@pytest.fixture
def client(db_session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    app.dependency_overrides[enforce_programme_watch_write_limit] = lambda: seeded["user"]
    app.dependency_overrides[enforce_account_export_limit] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        for dependency in (
            get_db,
            get_current_user,
            enforce_programme_watch_write_limit,
            enforce_account_export_limit,
        ):
            app.dependency_overrides.pop(dependency, None)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/calendar/watches"),
        ("put", "/calendar/missing/watch"),
        ("delete", "/calendar/missing/watch"),
    ],
)
def test_watches_require_auth(method, path):
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as anonymous:
            response = getattr(anonymous, method)(path)
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 401


def test_put_is_idempotent_and_captures_current_signature(client, db_session, seeded):
    programme = seeded["programme"]
    path = f"/calendar/{programme.slug}/watch"
    first = client.put(path)
    assert first.status_code == 200
    row = db_session.get(models.ProgrammeWatch, first.json()["id"])
    assert row.user_id == seeded["user"].id
    assert row.notified_signature == programme_signature(programme, now=datetime.now(timezone.utc))
    assert row.notified_at is None
    original_signature = row.notified_signature

    # A retry must preserve the watch-time baseline, even after the source changes.
    programme.editions[0].status = "announced"
    db_session.flush()
    second = client.put(path)
    assert second.status_code == 200
    assert second.json() == first.json()
    db_session.refresh(row)
    assert row.notified_signature == original_signature
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(models.ProgrammeWatch)
            .where(models.ProgrammeWatch.user_id == seeded["user"].id)
        )
        == 1
    )


def test_new_watch_does_not_notify_for_state_at_watch_time(client, db_session, seeded):
    from pipeline.programme_watch_notifications import collect_programme_watch_changes

    response = client.put(f"/calendar/{seeded['programme'].slug}/watch")
    assert response.status_code == 200
    assert (
        collect_programme_watch_changes(db_session, seeded["user"], datetime.now(timezone.utc)) == 0
    )
    assert (
        db_session.scalar(
            select(models.Notification.id).where(
                models.Notification.user_id == seeded["user"].id,
                models.Notification.type == "programme_watch",
            )
        )
        is None
    )


def test_delete_is_idempotent_and_only_deletes_my_watch(client, db_session, seeded):
    programme = seeded["programme"]
    other = models.ProgrammeWatch(user_id=seeded["other"].id, programme_id=programme.id)
    db_session.add(other)
    db_session.flush()
    other_id = other.id
    path = f"/calendar/{programme.slug}/watch"
    assert client.put(path).status_code == 200
    assert client.delete(path).status_code == 204
    assert client.delete(path).status_code == 204
    assert (
        db_session.scalar(
            select(models.ProgrammeWatch).where(models.ProgrammeWatch.user_id == seeded["user"].id)
        )
        is None
    )
    assert db_session.get(models.ProgrammeWatch, other_id) is not None


@pytest.mark.parametrize("method", ["put", "delete"])
def test_unknown_slug_returns_404(client, method):
    assert getattr(client, method)("/calendar/unknown-watch-programme/watch").status_code == 404


def test_cannot_start_watch_for_inactive_programme(client, db_session, seeded):
    seeded["programme"].is_active = False
    db_session.flush()
    assert client.put(f"/calendar/{seeded['programme'].slug}/watch").status_code == 404


def test_watch_cap_allows_idempotent_put_but_rejects_fifty_first(client, db_session, seeded):
    programmes = [seeded["programme"], *[_programme(index) for index in range(50)]]
    db_session.add_all(programmes)
    db_session.flush()
    db_session.add_all(
        models.ProgrammeWatch(user_id=seeded["user"].id, programme_id=programme.id)
        for programme in programmes[:50]
    )
    db_session.flush()
    assert client.put(f"/calendar/{programmes[0].slug}/watch").status_code == 200
    rejected = client.put(f"/calendar/{programmes[50].slug}/watch")
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "Programme watch limit of 50 reached"


def test_watch_list_is_private_and_never_shared_cached(client, db_session, seeded):
    programme = seeded["programme"]
    own = client.put(f"/calendar/{programme.slug}/watch").json()
    first = client.get("/calendar/watches")
    assert first.status_code == 200
    assert first.headers["Cache-Control"] == "no-store"
    assert "X-Cache" not in first.headers
    assert first.json() == [own]
    app.dependency_overrides[get_current_user] = lambda: seeded["other"]
    second = client.get("/calendar/watches")
    assert second.status_code == 200
    assert second.json() == []


def test_export_includes_only_my_watches(client, db_session, seeded):
    programme = seeded["programme"]
    client.put(f"/calendar/{programme.slug}/watch")
    other_programme = _programme(1)
    db_session.add(other_programme)
    db_session.flush()
    db_session.add(
        models.ProgrammeWatch(user_id=seeded["other"].id, programme_id=other_programme.id)
    )
    db_session.flush()
    response = client.get("/account/export")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    exported = response.json()["programme_watches"]
    assert len(exported) == 1
    assert exported[0]["programme_slug"] == programme.slug
    assert exported[0]["programme_name"] == programme.name
    assert exported[0]["programme_url"] == programme.url
    assert exported[0]["created_at"]
    assert "notified_signature" not in exported[0]


@pytest.mark.parametrize("parent", ["user", "programme"])
def test_deleting_parent_cascades_watch_at_database_level(db_session, seeded, parent):
    watch = models.ProgrammeWatch(user_id=seeded["user"].id, programme_id=seeded["programme"].id)
    db_session.add(watch)
    db_session.flush()
    watch_id = watch.id
    model = models.User if parent == "user" else models.Programme
    db_session.execute(delete(model).where(model.id == seeded[parent].id))
    db_session.flush()
    assert (
        db_session.scalar(
            select(models.ProgrammeWatch.id).where(models.ProgrammeWatch.id == watch_id)
        )
        is None
    )


def test_watch_uniqueness_is_enforced_by_database(db_session, seeded):
    values = {"user_id": seeded["user"].id, "programme_id": seeded["programme"].id}
    db_session.add(models.ProgrammeWatch(**values))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(models.ProgrammeWatch(**values))
        db_session.flush()


def test_unwatch_discards_pending_email_before_rewatch(client, db_session, seeded):
    from pipeline.programme_watch_notifications import programme_watch_updates

    programme = seeded["programme"]
    path = f"/calendar/{programme.slug}/watch"
    assert client.put(path).status_code == 200
    notification = models.Notification(
        user_id=seeded["user"].id,
        type="programme_watch",
        channel="in_app",
        status="sent",
        sent_at=datetime.now(timezone.utc),
        meta={"programme_id": programme.id, "email_pending": True},
    )
    db_session.add(notification)
    db_session.flush()
    assert client.delete(path).status_code == 204
    db_session.refresh(notification)
    assert notification.meta["email_pending"] is False
    assert client.put(path).status_code == 200
    assert programme_watch_updates(db_session, seeded["user"], datetime.now(timezone.utc)) == []
