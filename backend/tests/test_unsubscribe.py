"""One-click unsubscribe (core/unsubscribe.py + the /notifications/unsubscribe route).

This endpoint is deliberately UNAUTHENTICATED - Gmail POSTs to it on a reader's
behalf with no session. The token is the only thing standing between an
anonymous caller and someone else's preferences, so most of these tests are
about what a forged or tampered token must NOT achieve.
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from core import models, unsubscribe as unsubscribe_module
from core.config import get_settings
from core.unsubscribe import (
    key_fingerprint,
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
    """Pin the explicit key so tests never depend on runner credentials.

    Production proved that letting GitHub Actions and Render derive from their
    separate DATABASE_URL strings made every verification fail, so the tests
    exercise the dedicated-secret path by default.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "unsubscribe_secret", "pinned-test-key-do-not-use-in-prod")
    monkeypatch.setattr(settings, "database_url", "postgresql://fallback.invalid/aspirova")
    monkeypatch.setattr(settings, "api_base_url", "https://api.example.test")
    monkeypatch.setattr(unsubscribe_module, "_fallback_warning_emitted", False)


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


def test_token_round_trips_with_explicit_unsubscribe_secret():
    token = make_token(_UID_A, "hackathon_digest")
    assert token, "signing key must be configured in this environment"
    assert verify_token(token) == (str(_UID_A), "hackathon_digest")


def test_token_signed_under_a_different_secret_fails(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "unsubscribe_secret", "first-explicit-secret")
    token = make_token(_UID_A, "daily_digest")

    monkeypatch.setattr(settings, "unsubscribe_secret", "different-explicit-secret")
    assert verify_token(token) is None


def test_key_fingerprint_is_stable_distinct_and_empty_without_a_key(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "unsubscribe_secret", "first-explicit-secret")
    first = key_fingerprint()

    assert len(first) == 12
    assert key_fingerprint() == first

    monkeypatch.setattr(settings, "unsubscribe_secret", "different-explicit-secret")
    assert key_fingerprint() != first

    monkeypatch.setattr(settings, "unsubscribe_secret", "")
    monkeypatch.setattr(settings, "database_url", "")
    assert key_fingerprint() == ""


def test_database_url_fallback_warns_only_once_per_process(monkeypatch, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "unsubscribe_secret", "")

    with caplog.at_level("WARNING", logger="core.unsubscribe"):
        unsubscribe_module._signing_key()
        unsubscribe_module._signing_key()

    fallback_warnings = [
        record for record in caplog.records if "DATABASE_URL-derived" in record.message
    ]
    assert len(fallback_warnings) == 1
    assert "GitHub Actions and Render" in fallback_warnings[0].message


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
    from api.notifications import _apply_unsubscribe

    user = models.User(
        email=f"unsub-{uuid.uuid4()}@example.com",
        notification_prefs={"daily_digest": True, "instant_alerts": True},
    )
    db_session.add(user)
    db_session.flush()

    outcome = _apply_unsubscribe(token=make_token(user.id, "hackathon_digest"), db=db_session)
    db_session.refresh(user)

    assert outcome == "unsubscribed"
    assert user.notification_prefs["hackathon_digest"] is False
    assert user.notification_prefs["daily_digest"] is True, "must not touch other lists"
    assert user.notification_prefs["instant_alerts"] is True


def test_invalid_token_changes_nothing_and_still_answers_200(db_session):
    """Gmail treats a non-2xx as a broken unsubscribe, and an anonymous caller
    must not learn whether a user exists."""
    from api.notifications import unsubscribe_post

    user = models.User(
        email=f"unsub-{uuid.uuid4()}@example.com",
        notification_prefs={"daily_digest": True},
    )
    db_session.add(user)
    db_session.flush()

    response = unsubscribe_post(token="forged.deadbeef", db=db_session)
    db_session.refresh(user)

    assert response.status_code == 200
    assert "didn't work" in response.body.decode()
    assert "Open email settings" in response.body.decode()
    assert user.notification_prefs == {"daily_digest": True}


def test_apply_unsubscribe_distinguishes_invalid_token_from_missing_user(db_session):
    from api.notifications import _apply_unsubscribe

    assert _apply_unsubscribe(token="forged.deadbeef", db=db_session) == "invalid"
    missing_user_token = make_token(uuid.uuid4(), "daily_digest")
    assert _apply_unsubscribe(token=missing_user_token, db=db_session) == "no_user"


# ------------------------------------------------- GET must not mutate anything


def test_get_only_asks_and_changes_nothing(db_session):
    """The reason this endpoint is split by method.

    List-Unsubscribe is fetched by machines. Gmail POSTs it (RFC 8058), but
    security scanners, link previewers and corporate mail gateways issue GETs on
    every URL they find in a message, with no human involved. While GET
    unsubscribed, any such prefetch silently opted a reader out of mail they
    never asked to stop - and adding a VISIBLE unsubscribe link to the email
    body multiplies how often that happens.
    """
    from api.notifications import unsubscribe_get

    user = models.User(
        email=f"unsub-get-{uuid.uuid4()}@example.com",
        notification_prefs={"daily_digest": True, "hackathon_digest": True},
    )
    db_session.add(user)
    db_session.flush()

    response = unsubscribe_get(token=make_token(user.id, "hackathon_digest"), db=db_session)
    db_session.refresh(user)

    assert response.status_code == 200
    assert user.notification_prefs == {
        "daily_digest": True,
        "hackathon_digest": True,
    }, "a GET must never unsubscribe - scanners issue them unprompted"


def test_get_offers_a_form_that_posts_the_same_token(db_session):
    """The confirmation has to actually work: it must POST, and it must carry
    the token in the query string, because that is where the POST handler reads
    it from and where Gmail's one-click puts it."""
    from api.notifications import unsubscribe_get

    user = models.User(email=f"unsub-form-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    token = make_token(user.id, "daily_digest")
    body = unsubscribe_get(token=token, db=db_session).body.decode()

    assert 'method="post"' in body
    assert "/notifications/unsubscribe?token=" in body
    assert "<button" in body


def test_post_still_unsubscribes_in_one_shot(db_session):
    """Gmail's one-click gets no confirmation step - that is the whole contract
    of List-Unsubscribe-Post, and breaking it would put the digests back to
    being accepted and discarded."""
    from api.notifications import unsubscribe_post

    user = models.User(
        email=f"unsub-post-{uuid.uuid4()}@example.com",
        notification_prefs={"daily_digest": True},
    )
    db_session.add(user)
    db_session.flush()

    response = unsubscribe_post(token=make_token(user.id, "daily_digest"), db=db_session)
    db_session.refresh(user)

    assert response.status_code == 200
    assert "daily opportunity digest" in response.body.decode()
    assert user.notification_prefs["daily_digest"] is False


def test_missing_user_is_presented_as_success(db_session):
    from api.notifications import unsubscribe_post

    response = unsubscribe_post(
        token=make_token(uuid.uuid4(), "hackathon_digest"),
        db=db_session,
    )

    assert response.status_code == 200
    assert "You've been unsubscribed." in response.body.decode()
    assert "hackathon digest" in response.body.decode()
