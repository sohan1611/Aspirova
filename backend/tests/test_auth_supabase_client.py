import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from api import auth
from core import models

USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
AUTH_USER = {"id": str(USER_ID), "email": "student@example.test"}
DEAD_CONNECTION_ERRORS = [httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError]


@pytest.fixture(autouse=True)
def _auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://supabase.example.test",
            supabase_anon_key="test-anon-key",
        ),
    )


@pytest.fixture
def supabase_request(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    handler = MagicMock(return_value=httpx.Response(200, json=AUTH_USER))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(auth, "_supabase_http", client)
        yield handler


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.get.return_value = models.User(id=USER_ID, email=AUTH_USER["email"])
    return session


def test_200_returns_mirrored_user(supabase_request, db) -> None:
    user = auth.get_current_user(authorization="Bearer test-token", db=db)

    assert user is db.get.return_value
    db.get.assert_called_once_with(models.User, USER_ID)
    db.add.assert_not_called()
    db.commit.assert_not_called()
    assert supabase_request.call_count == 1
    request = supabase_request.call_args.args[0]
    assert request.method == "GET"
    assert str(request.url) == "https://supabase.example.test/auth/v1/user"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["apikey"] == "test-anon-key"


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_non_200_raises_401(supabase_request, db, status_code) -> None:
    supabase_request.return_value = httpx.Response(status_code)

    with pytest.raises(auth.HTTPException) as exc:
        auth.get_current_user(authorization="Bearer test-token", db=db)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid or expired token"
    assert supabase_request.call_count == 1
    db.get.assert_not_called()


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.TimeoutException])
def test_outage_raises_503_without_retry(supabase_request, db, error_type) -> None:
    supabase_request.side_effect = error_type("Auth unavailable")

    with pytest.raises(auth.HTTPException) as exc:
        auth.get_current_user(authorization="Bearer test-token", db=db)

    assert exc.value.status_code == 503
    assert exc.value.detail == "Auth service unavailable"
    assert supabase_request.call_count == 1
    db.get.assert_not_called()


@pytest.mark.parametrize("error_type", DEAD_CONNECTION_ERRORS)
def test_dead_connection_then_200_succeeds(supabase_request, db, error_type) -> None:
    supabase_request.side_effect = [
        error_type("Connection closed"),
        httpx.Response(200, json=AUTH_USER),
    ]

    assert auth.get_current_user(authorization="Bearer test-token", db=db) is db.get.return_value
    assert supabase_request.call_count == 2
    db.get.assert_called_once_with(models.User, USER_ID)


@pytest.mark.parametrize("error_type", DEAD_CONNECTION_ERRORS)
def test_dead_connection_twice_raises_503(supabase_request, db, error_type) -> None:
    supabase_request.side_effect = [error_type("Connection closed"), error_type("Still closed")]

    with pytest.raises(auth.HTTPException) as exc:
        auth.get_current_user(authorization="Bearer test-token", db=db)

    assert exc.value.status_code == 503
    assert exc.value.detail == "Auth service unavailable"
    assert supabase_request.call_count == 2
    db.get.assert_not_called()


def test_missing_user_is_mirrored(supabase_request, db) -> None:
    mirrored = models.User(id=USER_ID, email=AUTH_USER["email"])
    db.get.side_effect = [None, mirrored]

    user = auth.get_current_user(authorization="Bearer test-token", db=db)

    assert user is mirrored
    assert db.get.call_count == 2
    db.execute.assert_called_once()
    db.add.assert_not_called()
    db.commit.assert_called_once_with()
    assert supabase_request.call_count == 1
