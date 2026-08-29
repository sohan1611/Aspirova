"""One-click unsubscribe (core/unsubscribe.py + the /notifications/unsubscribe route).

This endpoint is deliberately UNAUTHENTICATED - Gmail POSTs to it on a reader's
behalf with no session. The token is the only thing standing between an
anonymous caller and someone else's preferences, so most of these tests are
about what a forged or tampered token must NOT achieve.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from core import models
from core.unsubscribe import (
    list_unsubscribe_headers,
    make_token,
    unsubscribe_url,
    verify_token,
)

# Real UUIDs, because users.id is a UUID mirroring Supabase auth.users.id.
# The first version of these tests used integers and passed while the feature
# was completely broken in production.
_UID_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
_UID_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture(autouse=True)
def _pinned_signing_key(monkeypatch):
    """Pin the key so these tests never depend on which secrets an environment
    happens to carry. CI failed exactly that way once: it has no
    SUPABASE_SERVICE_KEY, the key came back empty, and every token was blank -
    which was a real production bug, but the tests should have been asserting
    logic rather than reporting on the runner's env."""
    monkeypatch.setattr(
        "core.unsubscribe._signing_key", lambda: b"pinned-test-key-do-not-use-in-prod"
    )


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


# --------------------------------------------------------------- token round trip


def test_token_round_trips():
    token = make_token(_UID_A, "hackathon_digest")
    assert token, "signing key must be configured in this environment"
    assert verify_token(token) == (str(_UID_A), "hackathon_digest")


def test_token_is_bound_to_one_preference():
    """A token for one list must not silence a different one."""
    token = make_token(_UID_A, "hackathon_digest")
    user_id, preference = verify_token(token)
    assert preference == "hackathon_digest"
    assert preference != "daily_digest"


@pytest.mark.parametrize(
    "forged",
    [
        "",
        "nonsense",
        "no-dot-separator",
        "YWJj.deadbeef",  # well-formed shape, wrong signature
        "!!!not-base64!!!.deadbeef",
        ".",
        "." * 200,
    ],
)
def test_forged_tokens_are_rejected_without_raising(forged):
    """Anonymous callers reach this. Malformed input is a rejection, never a 500."""
    assert verify_token(forged) is None


def test_tampering_with_the_user_id_invalidates_the_signature():
    """The attack that matters: edit the payload to point at somebody else."""
    import base64

    original = make_token(_UID_A, "daily_digest")
    encoded, _, signature = original.partition(".")
    forged_payload = (
        base64.urlsafe_b64encode(f"{_UID_B}:daily_digest".encode()).decode().rstrip("=")
    )

    assert verify_token(f"{forged_payload}.{signature}") is None


def test_signature_of_one_user_cannot_be_replayed_for_another():
    a = make_token(_UID_A, "daily_digest")
    b = make_token(_UID_B, "daily_digest")
    assert a != b

    encoded_a, _, _ = a.partition(".")
    _, _, signature_b = b.partition(".")
    assert verify_token(f"{encoded_a}.{signature_b}") is None


# --------------------------------------------------------------- headers


def test_headers_carry_both_fields_gmail_requires():
    headers = list_unsubscribe_headers(_UID_A, "hackathon_digest")
    assert headers["List-Unsubscribe"].startswith("<http")
    assert headers["List-Unsubscribe"].endswith(">")
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_url_points_at_the_api_not_the_site():
    """The endpoint lives on the API. Pointing at the frontend would 404 for
    Gmail, which reads a non-2xx as a broken unsubscribe - the exact thing
    this change exists to fix."""
    url = unsubscribe_url(_UID_A, "daily_digest")
    assert "/notifications/unsubscribe?token=" in url


def test_headers_are_omitted_entirely_when_signing_is_unconfigured(monkeypatch):
    """A List-Unsubscribe pointing somewhere that cannot work is worse than
    none: the reader clicks, nothing happens, and they report spam instead."""
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"")
    assert list_unsubscribe_headers(_UID_A, "daily_digest") == {}


# --------------------------------------------------------------- endpoint effect


def test_unsubscribing_turns_off_only_the_named_preference(db_session):
    from api.notifications import unsubscribe

    user = models.User(
        email=f"unsub-{uuid.uuid4()}@example.com",
        notification_prefs={"daily_digest": True, "instant_alerts": True},
    )
    db_session.add(user)
    db_session.flush()

    unsubscribe(token=make_token(user.id, "hackathon_digest"), db=db_session)
    db_session.refresh(user)

    assert user.notification_prefs["hackathon_digest"] is False
    assert user.notification_prefs["daily_digest"] is True, "must not touch other lists"
    assert user.notification_prefs["instant_alerts"] is True


def test_invalid_token_changes_nothing_and_still_answers_200(db_session):
    """Gmail treats a non-2xx as a broken unsubscribe, and an anonymous caller
    must not learn whether a user exists."""
    from api.notifications import unsubscribe

    user = models.User(
        email=f"unsub-{uuid.uuid4()}@example.com",
        notification_prefs={"daily_digest": True},
    )
    db_session.add(user)
    db_session.flush()

    response = unsubscribe(token="forged.deadbeef", db=db_session)
    db_session.refresh(user)

    assert response.status_code == 200
    assert user.notification_prefs == {"daily_digest": True}
