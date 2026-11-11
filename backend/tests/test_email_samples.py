"""Pricing email examples must render without a database or real employer data."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from api.deps import get_db
from api.main import app
from core.email_samples import render_sample


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override conftest's DB cleanup: these tests must run with no database."""
    yield


@pytest.fixture
def client(monkeypatch):
    def no_database(*args, **kwargs):
        raise AssertionError("Email samples must not access a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = no_database
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("kind", ["company-alert", "weekly-report"])
def test_email_sample_is_public_fictional_and_cacheable(client, kind):
    response = client.get(f"/email-samples/{kind}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
    sample = response.json()
    assert sample["subject"].strip()
    html = sample["html"]
    assert "<html" in html
    for company in ("Northwind Labs", "Campus Loom", "Brightpath Analytics"):
        assert company in html
    for employer in ("Google", "Microsoft", "Razorpay", "Zomato"):
        assert employer.casefold() not in html.casefold()
    assert "https://example.com/careers/sample-role-" in html
    assert "https://www.aspirova.org/account?section=notifications" in html


def test_unknown_email_sample_returns_404_without_database(client):
    assert client.get("/email-samples/unknown").status_code == 404
    assert render_sample("unknown") is None


@pytest.mark.parametrize("kind", ["company-alert", "weekly-report"])
def test_sample_output_is_deterministic(client, kind):
    assert (
        client.get(f"/email-samples/{kind}").json() == client.get(f"/email-samples/{kind}").json()
    )


@pytest.mark.parametrize("kind", ["company-alert", "weekly-report"])
def test_samples_advertise_only_running_features(client, kind):
    """README 2026-11-03: Pro sells only what runs, and AI is deferred."""
    html = client.get(f"/email-samples/{kind}").json()["html"]

    assert "AI-assisted" not in html
    assert "AI-powered" not in html


def test_sample_dates_follow_today_so_no_deadline_is_past():
    """A fixed sample date would show deadlines in the past on the pricing page."""
    _subject, html = render_sample("weekly-report")
    _subject, fixed = render_sample(
        "weekly-report", now=datetime(2026, 11, 8, 9, tzinfo=timezone.utc)
    )

    assert "Deadline 10 Nov 2026" in fixed
    assert html != fixed or datetime.now(timezone.utc).date().isoformat() == "2026-11-08"
