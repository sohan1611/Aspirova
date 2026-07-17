"""POST /waitlist - the honest Razorpay dummy (Doc handoffs/
PHASE-2.5-HANDOFF.md sec 3.7). WAITLIST_NOTIFY_EMAIL is unset in this
environment, so a valid signup never triggers a real Resend send - see
core/email_client.py's own blank-config no-op behavior."""

from fastapi.testclient import TestClient

from api import waitlist
from api.main import app

client = TestClient(app)


def test_invalid_email_returns_422() -> None:
    response = client.post("/waitlist", json={"email": "not-an-email"})
    assert response.status_code == 422


def test_valid_email_returns_ok() -> None:
    response = client.post("/waitlist", json={"email": "waitlist-test@example.com"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_signup_email_is_html_escaped_in_notification(monkeypatch) -> None:
    email = "<b>&\"'</b>@x.co"
    sent_emails: list[dict[str, str]] = []

    def fake_send(*, to: str, subject: str, html: str, text: str) -> bool:
        sent_emails.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(waitlist.get_settings(), "waitlist_notify_email", "founder@example.com")
    monkeypatch.setattr(waitlist, "get_redis", lambda: None)
    monkeypatch.setattr(waitlist, "send_email", fake_send)

    response = client.post("/waitlist", json={"email": email})

    assert response.status_code == 200
    assert len(sent_emails) == 1
    assert sent_emails[0]["html"] == (
        "<p>New waitlist signup: &lt;b&gt;&amp;&quot;&#x27;&lt;/b&gt;@x.co</p>"
    )
    assert "<b>" not in sent_emails[0]["html"]
    assert sent_emails[0]["text"] == f"New waitlist signup: {email}"
