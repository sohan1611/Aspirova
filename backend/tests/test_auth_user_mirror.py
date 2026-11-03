"""Integration tests for first-request Supabase user mirroring."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import api.auth as auth_module
from api.auth import get_current_user
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
def auth_payload(monkeypatch: pytest.MonkeyPatch) -> dict:
    user_id = uuid.uuid4()
    payload = {
        "id": str(user_id),
        "email": f"auth-mirror-test-{user_id}@example.com",
    }

    class StubResponse:
        status_code = 200

        def json(self) -> dict:
            return payload

    monkeypatch.setattr(auth_module, "_get_supabase_user", lambda *args, **kwargs: StubResponse())
    return payload


def test_simultaneous_first_requests_create_one_user(engine, auth_payload: dict) -> None:
    user_id = uuid.UUID(auth_payload["id"])
    barrier = threading.Barrier(16)

    def authenticate(_: int) -> uuid.UUID:
        with Session(bind=engine) as session:
            barrier.wait(timeout=30)
            return get_current_user(authorization="Bearer x", db=session).id

    # Separate connections must see committed rows; an outer rollback cannot clean these up.
    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            returned_ids = list(executor.map(authenticate, range(16)))

        assert returned_ids == [user_id] * 16
        with Session(bind=engine) as session:
            count = session.scalar(
                select(func.count()).select_from(models.User).where(models.User.id == user_id)
            )
            assert count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(delete(models.User).where(models.User.id == user_id))


@pytest.mark.parametrize(
    ("auth_fields", "expected"),
    [
        pytest.param(
            {"user_metadata": {"full_name": "Ada Lovelace", "name": "Other Name"}},
            "Ada Lovelace",
            id="full-name-first",
        ),
        pytest.param(
            {"user_metadata": {"name": "Grace Hopper"}}, "Grace Hopper", id="name-fallback"
        ),
        pytest.param(
            {"user_metadata": {"full_name": 42, "name": "Grace Hopper"}},
            "Grace Hopper",
            id="first-string",
        ),
        pytest.param({}, None, id="missing-metadata"),
        pytest.param({"user_metadata": None}, None, id="null-metadata"),
        pytest.param({"user_metadata": "Ada Lovelace"}, None, id="string-metadata"),
        pytest.param({"user_metadata": ["Ada Lovelace"]}, None, id="list-metadata"),
        pytest.param({"user_metadata": {}}, None, id="missing-name"),
        pytest.param({"user_metadata": {"full_name": 42}}, None, id="non-string-name"),
        pytest.param({"user_metadata": {"full_name": " \t\n "}}, None, id="blank-name"),
        pytest.param({"user_metadata": {"full_name": "ada@example.com"}}, None, id="email-name"),
        pytest.param(
            {"user_metadata": {"full_name": "  A\x00da\x7f \n\t\r Love\x07lace  "}},
            "Ada Lovelace",
            id="control-characters-and-whitespace",
        ),
        pytest.param(
            {"user_metadata": {"full_name": "Ada\nLovelace"}},
            "Ada Lovelace",
            id="newline-between-names",
        ),
        pytest.param({"user_metadata": {"full_name": "A" * 80}}, "A" * 80, id="maximum-length"),
        pytest.param({"user_metadata": {"full_name": "A" * 81}}, None, id="over-maximum-length"),
    ],
)
def test_new_user_provider_display_name(
    db_session: Session, auth_payload: dict, auth_fields: dict, expected: str | None
) -> None:
    auth_payload.update(auth_fields)

    user = get_current_user(authorization="Bearer x", db=db_session)

    assert user.id == uuid.UUID(auth_payload["id"])
    assert user.display_name == expected
    db_session.refresh(user)
    assert user.display_name == expected


@pytest.mark.parametrize("existing_name", ["Chosen Name", None])
def test_existing_user_keeps_display_name(
    db_session: Session, auth_payload: dict, existing_name: str | None
) -> None:
    existing_user = models.User(
        id=uuid.UUID(auth_payload["id"]),
        email=auth_payload["email"],
        display_name=existing_name,
    )
    db_session.add(existing_user)
    db_session.flush()
    auth_payload["user_metadata"] = {"full_name": "Provider Name"}

    user = get_current_user(authorization="Bearer x", db=db_session)

    assert user.id == existing_user.id
    db_session.refresh(user)
    assert user.display_name == existing_name


def test_email_owned_by_another_id_returns_conflict(
    db_session: Session, auth_payload: dict, caplog: pytest.LogCaptureFixture
) -> None:
    existing_id = uuid.uuid4()
    new_id = uuid.UUID(auth_payload["id"])
    db_session.add(models.User(id=existing_id, email=auth_payload["email"]))
    db_session.flush()

    with caplog.at_level("WARNING", logger="api.auth"):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(authorization="Bearer x", db=db_session)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Account conflict. Please contact support."
    assert db_session.get(models.User, new_id) is None
    assert db_session.get(models.User, existing_id) is not None
    assert str(new_id) in caplog.text
    assert auth_payload["email"] not in caplog.text
