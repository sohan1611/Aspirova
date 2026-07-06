"""POST /waitlist - the honest Razorpay dummy (Doc handoffs/
PHASE-2.5-HANDOFF.md sec 3.7). WAITLIST_NOTIFY_EMAIL is unset in this
environment, so a valid signup never triggers a real Resend send - see
core/email_client.py's own blank-config no-op behavior."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_invalid_email_returns_422() -> None:
    response = client.post("/waitlist", json={"email": "not-an-email"})
    assert response.status_code == 422


def test_valid_email_returns_ok() -> None:
    response = client.post("/waitlist", json={"email": "waitlist-test@example.com"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
