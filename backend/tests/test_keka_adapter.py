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


def test_fetch_non_list_payload_is_degraded_and_returns_no_listings(
    monkeypatch: pytest.MonkeyPatch, keka_jobs: list[dict[str, Any]]
) -> None:
    adapter = KekaAdapter(TENANT, COMPANY_NAME)
    _mock_keka_get(monkeypatch, adapter, {"jobs": keka_jobs})

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"


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
