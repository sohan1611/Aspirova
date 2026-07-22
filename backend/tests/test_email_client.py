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


def test_send_email_returns_false_when_unconfigured(monkeypatch) -> None:
    # send_email calls get_settings() internally - there is no module-level
    # `settings` attribute to patch, so patch the factory instead.
    monkeypatch.setattr(
        email_client,
        "get_settings",
        lambda: SimpleNamespace(
            resend_api_key="",
            resend_from_email="noreply@aspirova.org",
            resend_from_name="Aspirova",
        ),
    )

    assert (
        email_client.send_email(
            to="student@example.com",
            subject="Test email",
            html="<p>Test email</p>",
            text="Test email",
        )
        is False
    )
