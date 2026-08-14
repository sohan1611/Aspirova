"""Offline tests for the Keka ATS adapter."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.adapters import RawListing
from crawlers.keka import KekaAdapter
from pipeline.normalize import classify_category

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TENANT = "clickpost"
COMPANY_NAME = "ClickPost"
TENANT_UUID = "5f7d5bd9-3af5-4cb2-b24e-57cd7d1c9f31"
ROOT_URL = f"https://{TENANT}.keka.com/careers/"
API_URL = f"https://{TENANT}.keka.com/careers/api/embedjobs/default/active/{TENANT_UUID}"


@pytest.fixture
def keka_jobs() -> list[dict[str, Any]]:
    return json.loads((FIXTURES_DIR / "keka_sample.json").read_text(encoding="utf-8"))


def _response(
    url: str,
    *,
    status_code: int = 200,
    json_data: Any | None = None,
    text: str | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", url)
    if text is not None:
        return httpx.Response(status_code, text=text, request=request)
    return httpx.Response(status_code, json=json_data, request=request)


def _mock_keka_get(
    monkeypatch: pytest.MonkeyPatch,
    adapter: KekaAdapter,
    jobs: Any,
    *,
    root_html: str | None = None,
) -> list[str]:
    calls: list[str] = []
    html = root_html or f'<script>const tenantId = "{TENANT_UUID}";</script>'

    def fake_get(url: str, **_: Any) -> httpx.Response:
        calls.append(url)
        if url == ROOT_URL:
            return _response(url, text=html)
        if url == API_URL:
            return _response(url, json_data=jobs)
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setattr(adapter._client, "get", fake_get)
    return calls


def _remote_test_listing(title: str, location: str) -> RawListing:
    return RawListing(
        source_slug="keka",
        external_id="remote-test",
        source_url="https://clickpost.keka.com/careers/jobdetails/remote-test",
        raw_payload={
            "id": "remote-test",
            "title": title,
            "jobLocations": [{"city": location}],
        },
        content_hash="remote-test",
    )


def test_adapter_identity_and_default_health() -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)

    assert adapter.source_slug == "keka"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_fetch_extracts_first_uuid_and_parses_jobs(
    monkeypatch: pytest.MonkeyPatch, keka_jobs: list[dict[str, Any]]
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    calls = _mock_keka_get(
        monkeypatch,
        adapter,
        keka_jobs,
        root_html=(
            f'<meta name="tenant" content="{TENANT_UUID}">'
            '<script>const anotherId = "a3e969b5-894c-4d70-9770-1d74daf5d6db";</script>'
        ),
    )

    raw_listings = adapter.fetch()

    assert calls == [ROOT_URL, API_URL]
    assert adapter.health() == "ok"
    assert [listing.external_id for listing in raw_listings] == [
        "134778",
        "134779",
        "134780",
    ]
    assert raw_listings[0].source_url == ("https://clickpost.keka.com/careers/jobdetails/134778")

    parsed = adapter.parse(raw_listings[0])

    assert parsed.title == "Software Engineering Intern"
    assert parsed.company_name == COMPANY_NAME
    assert parsed.location == "Hyderabad, TG, India"
    assert "Build reliable tools for students." in parsed.description_raw
    assert parsed.apply_url == "https://clickpost.keka.com/careers/jobdetails/134778"
    assert parsed.posted_at is not None
    assert parsed.category == classify_category("Software Engineering Intern")


def test_parse_handles_empty_locations_and_missing_published_on(
    monkeypatch: pytest.MonkeyPatch, keka_jobs: list[dict[str, Any]]
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    _mock_keka_get(monkeypatch, adapter, keka_jobs)

    raw_listing = adapter.fetch()[1]
    parsed = adapter.parse(raw_listing)

    assert parsed.location == ""
    assert parsed.posted_at is None
    assert parsed.description_raw == "Build backend services for customers."


def test_parse_marks_remote_title_as_remote(
    monkeypatch: pytest.MonkeyPatch, keka_jobs: list[dict[str, Any]]
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    _mock_keka_get(monkeypatch, adapter, keka_jobs)

    parsed = adapter.parse(adapter.fetch()[2])

    assert parsed.is_remote is True


@pytest.mark.parametrize("title", ["Remote Sensing Engineer", "Remote Sensor Lead"])
def test_parse_does_not_mark_remote_descriptors_as_remote(title: str) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)

    parsed = adapter.parse(_remote_test_listing(title, "Bengaluru"))

    assert parsed.is_remote is False


def test_parse_marks_remote_software_title_as_remote() -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)

    parsed = adapter.parse(_remote_test_listing("Remote Software Engineer", "Bengaluru"))

    assert parsed.is_remote is True


def test_parse_marks_remote_location_as_remote() -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)

    parsed = adapter.parse(_remote_test_listing("Software Engineer", "Remote"))

    assert parsed.is_remote is True


def test_parse_marks_ordinary_on_site_title_as_not_remote() -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)

    parsed = adapter.parse(_remote_test_listing("Software Engineer", "Bengaluru"))

    assert parsed.is_remote is False


def test_parse_handles_garbage_payload_without_raising() -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    raw_listing = RawListing(
        source_slug="keka",
        external_id="malformed",
        source_url="https://clickpost.keka.com/careers/jobdetails/malformed",
        raw_payload={
            "id": [],
            "title": {"unexpected": "object"},
            "description": ["unexpected", "list"],
            "excerpt": {"unexpected": "object"},
            "jobLocations": {"unexpected": "object"},
            "publishedOn": ["unexpected", "list"],
        },
        content_hash="garbage-payload",
    )

    parsed = adapter.parse(raw_listing)

    assert parsed.external_id == "malformed"
    assert parsed.title == ""
    assert parsed.location == ""
    assert parsed.description_raw == ""
    assert parsed.posted_at is None


def test_fetch_marks_broken_for_error_object_instead_of_jobs_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    _mock_keka_get(monkeypatch, adapter, {"error": "unknown tenant"})

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


def test_fetch_accepts_empty_jobs_list(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    _mock_keka_get(monkeypatch, adapter, [])

    assert adapter.fetch() == []
    assert adapter.health() == "ok"


def test_fetch_marks_broken_for_invalid_jobs_json(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    html = f'<script>const tenantId = "{TENANT_UUID}";</script>'

    def fake_get(url: str, **_: Any) -> httpx.Response:
        if url == ROOT_URL:
            return _response(url, text=html)
        if url == API_URL:
            return _response(url, text="not JSON")
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setattr(adapter._client, "get", fake_get)

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


def test_fetch_missing_uuid_is_broken_and_returns_no_listings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    calls = _mock_keka_get(
        monkeypatch,
        adapter,
        [],
        root_html="<html><body>No tenant identifier is present.</body></html>",
    )

    assert adapter.fetch() == []
    assert adapter.health() == "broken"
    assert calls == [ROOT_URL]


@pytest.mark.parametrize(
    ("status_code", "expected_health"),
    [(404, "broken"), (500, "degraded")],
)
def test_fetch_preserves_careers_endpoint_http_failure_health(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_health: str,
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    monkeypatch.setattr(
        adapter._client,
        "get",
        lambda url, **_kwargs: _response(url, status_code=status_code, text="unavailable"),
    )

    assert adapter.fetch() == []
    assert adapter.health() == expected_health


def test_fetch_preserves_careers_endpoint_request_error_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)

    def raise_request_error(_url: str, **_kwargs: Any) -> httpx.Response:
        raise httpx.RequestError("network unavailable")

    monkeypatch.setattr(adapter._client, "get", raise_request_error)

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"
