from types import SimpleNamespace

import core.email_client as email_client


def test_format_from_adds_default_display_name() -> None:
    assert (
        email_client._format_from("Aspirova", "noreply@aspirova.org")
        == "Aspirova <noreply@aspirova.org>"
    )


def test_format_from_preserves_preformatted_address() -> None:
    sender = "Name <noreply@aspirova.org>"

    assert email_client._format_from("Aspirova", sender) == sender


def test_format_from_uses_bare_address_for_blank_name() -> None:
    assert email_client._format_from("   ", "noreply@aspirova.org") == "noreply@aspirova.org"


def test_format_from_quotes_display_name_with_comma() -> None:
    assert (
        email_client._format_from("A, B", "noreply@aspirova.org") == '"A, B" <noreply@aspirova.org>'
    )


def test_transport_reports_unconfigured_without_network(monkeypatch) -> None:
    monkeypatch.setattr(
        email_client,
        "get_settings",
        lambda: SimpleNamespace(resend_api_key="", resend_from_email="noreply@example.test"),
    )
    monkeypatch.setattr(
        email_client.httpx,
        "post",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Unconfigured transport must not make HTTP")
        ),
    )
    result = email_client._transport({"text": "test"}, "email/test")
    assert result.provider_id is None
    assert result.code == 503


def test_plain_transactional_email_omits_html(monkeypatch) -> None:
    from core import email_outbox
    from unittest.mock import Mock

    captured = []
    session = Mock()
    monkeypatch.setattr(
        email_outbox,
        "get_settings",
        lambda: SimpleNamespace(
            resend_from_email="noreply@example.test", resend_from_name="Aspirova"
        ),
    )
    monkeypatch.setattr(
        email_outbox,
        "enqueue",
        lambda *args, **kwargs: captured.append(kwargs) or SimpleNamespace(id=123),
    )
    monkeypatch.setattr(email_outbox, "attempt_delivery", lambda *args, **kwargs: True)
    assert email_client.send_email(
        "deleted@example.test",
        "Account deleted",
        "",
        "Account deleted.",
        session=session,
        kind="account_deleted",
        identity="event-123",
    )
    payload = captured[0]["payload"]
    assert payload["text"] == "Account deleted."
    assert "html" not in payload
    assert captured[0]["kind"] == "account_deleted"
    session.commit.assert_called_once()
