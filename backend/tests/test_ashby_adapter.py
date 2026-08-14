"""Unit tests for AshbyAdapter.parse() against a captured real payload
(tests/fixtures/ashby_notion_sample.json - a real internship posting plus
2 real word-boundary regression cases ("International Tax Manager"), all
fetched live from api.ashbyhq.com/posting-api/job-board/notion). No
network access required - fetch() uses stubbed responses.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.adapters import RawListing
from crawlers.ashby import AshbyAdapter
from crawlers.common import content_hash
from pipeline.normalize import classify_category

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ashby_notion_sample.json"


def _load_fixture_jobs() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(job: dict) -> RawListing:
    return RawListing(
        source_slug="ashby",
        external_id=job["id"],
        source_url=job["jobUrl"],
        content_hash=content_hash(job),
        raw_payload=job,
    )


class StubResponse:
    status_code = 200

    def __init__(self, payload: Any = None, *, json_error: bool = False) -> None:
        self._payload = payload
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error:
            raise ValueError("invalid JSON")
        return self._payload


@pytest.fixture
def adapter() -> AshbyAdapter:
    return AshbyAdapter(board_token="notion", company_name="Notion")


@pytest.fixture
def fixture_jobs() -> list[dict]:
    return _load_fixture_jobs()


def test_adapter_identity(adapter: AshbyAdapter) -> None:
    assert adapter.source_slug == "ashby"
    assert adapter.requires_browser is False


def test_health_defaults_to_ok_before_any_fetch(adapter: AshbyAdapter) -> None:
    assert adapter.health() == "ok"


def test_fetch_marks_broken_for_error_object_without_jobs(
    adapter: AshbyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        adapter._client,
        "get",
        lambda _url: StubResponse({"error": "unknown"}),
    )

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


def test_fetch_accepts_empty_jobs_container(
    adapter: AshbyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter._client, "get", lambda _url: StubResponse({"jobs": []}))

    assert adapter.fetch() == []
    assert adapter.health() == "ok"


def test_fetch_parses_fixture_jobs_and_marks_board_healthy(
    adapter: AshbyAdapter,
    fixture_jobs: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter._client,
        "get",
        lambda _url: StubResponse({"jobs": fixture_jobs}),
    )

    listings = adapter.fetch()

    assert adapter.health() == "ok"
    assert [listing.external_id for listing in listings] == [job["id"] for job in fixture_jobs]


def test_fetch_marks_broken_for_invalid_json(
    adapter: AshbyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter._client, "get", lambda _url: StubResponse(json_error=True))

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


@pytest.mark.parametrize(
    ("status_code", "expected_health"),
    [(404, "broken"), (500, "degraded")],
)
def test_fetch_preserves_http_failure_health(
    adapter: AshbyAdapter,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_health: str,
) -> None:
    response = StubResponse({"jobs": []})
    response.status_code = status_code
    monkeypatch.setattr(adapter._client, "get", lambda _url: response)

    assert adapter.fetch() == []
    assert adapter.health() == expected_health


def test_fetch_preserves_request_error_as_degraded(
    adapter: AshbyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_request_error(_url: str) -> StubResponse:
        raise httpx.RequestError("network unavailable")

    monkeypatch.setattr(adapter._client, "get", raise_request_error)

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"


def test_parse_internship_job(adapter: AshbyAdapter, fixture_jobs: list[dict]) -> None:
    job = next(j for j in fixture_jobs if j["title"] == "Software Engineer Intern (Fall 2026)")
    normalized = adapter.parse(_raw_listing_for(job))

    assert normalized.title == job["title"]
    assert normalized.company_name == "Notion"
    assert normalized.category == "internship"
    assert normalized.apply_url == job["jobUrl"]
    assert normalized.external_id == job["id"]
    assert normalized.deadline is None
    assert normalized.deadline_confidence == "unknown"


def test_parse_word_boundary_regression_international_tax_manager(
    adapter: AshbyAdapter, fixture_jobs: list[dict]
) -> None:
    """Real production case: "International Tax Manager" contains "intern"
    as a substring but is not an internship (same class of regression
    covered for Greenhouse in test_greenhouse_adapter.py)."""
    job = next(j for j in fixture_jobs if j["title"] == "International Tax Manager")
    normalized = adapter.parse(_raw_listing_for(job))

    assert normalized.category == "job"


def test_parse_uses_plain_text_description_directly(
    adapter: AshbyAdapter, fixture_jobs: list[dict]
) -> None:
    job = fixture_jobs[0]
    normalized = adapter.parse(_raw_listing_for(job))

    assert normalized.description_raw == job["descriptionPlain"]
    assert "<" not in normalized.description_raw


def test_parse_is_remote_comes_directly_from_api_boolean(
    adapter: AshbyAdapter, fixture_jobs: list[dict]
) -> None:
    """Ashby is the only source so far that gives isRemote as a direct
    boolean - no substring-of-location-name heuristic needed."""
    job = fixture_jobs[0]
    normalized = adapter.parse(_raw_listing_for(job))

    assert normalized.is_remote == job["isRemote"]


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Software Engineer Intern (Fall 2026)", "internship"),
        ("International Tax Manager", "job"),
        ("Lead, Internal Audit and SOX Compliance", "job"),
    ],
)
def test_classify_category_word_boundary_safety(title: str, expected: str) -> None:
    assert classify_category(title) == expected
