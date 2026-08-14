"""Unit tests for GreenhouseAdapter.parse() against a captured real payload
(tests/fixtures/greenhouse_cloudflare_sample.json - 2 real internships +
1 real non-internship job, fetched live from boards-api.greenhouse.io).
No network access required - fetch() uses stubbed responses.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.adapters import RawListing
from crawlers.greenhouse import GreenhouseAdapter, _content_hash
from pipeline.normalize import classify_category

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "greenhouse_cloudflare_sample.json"


def _load_fixture_jobs() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["jobs"]


def _raw_listing_for(job: dict) -> RawListing:
    return RawListing(
        source_slug="greenhouse",
        external_id=str(job["id"]),
        source_url=job["absolute_url"],
        content_hash=_content_hash(job),
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
def adapter() -> GreenhouseAdapter:
    return GreenhouseAdapter(board_token="cloudflare", company_name="Cloudflare")


@pytest.fixture
def fixture_jobs() -> list[dict]:
    return _load_fixture_jobs()


def test_adapter_identity(adapter: GreenhouseAdapter) -> None:
    assert adapter.source_slug == "greenhouse"
    assert adapter.requires_browser is False


def test_health_defaults_to_ok_before_any_fetch(adapter: GreenhouseAdapter) -> None:
    assert adapter.health() == "ok"


def test_fetch_marks_broken_for_error_object_without_jobs(
    adapter: GreenhouseAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        adapter._client,
        "get",
        lambda _url: StubResponse({"error": "unknown"}),
    )

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


def test_fetch_accepts_empty_jobs_container(
    adapter: GreenhouseAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter._client, "get", lambda _url: StubResponse({"jobs": []}))

    assert adapter.fetch() == []
    assert adapter.health() == "ok"


def test_fetch_parses_fixture_jobs_and_marks_board_healthy(
    adapter: GreenhouseAdapter,
    fixture_jobs: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter._client, "get", lambda _url: StubResponse({"jobs": fixture_jobs}))

    listings = adapter.fetch()

    assert adapter.health() == "ok"
    assert [listing.external_id for listing in listings] == [str(job["id"]) for job in fixture_jobs]


def test_fetch_marks_broken_for_invalid_json(
    adapter: GreenhouseAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter._client, "get", lambda _url: StubResponse(json_error=True))

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


@pytest.mark.parametrize(
    ("status_code", "expected_health"),
    [(404, "broken"), (500, "degraded")],
)
def test_fetch_preserves_http_failure_health(
    adapter: GreenhouseAdapter,
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
    adapter: GreenhouseAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_request_error(_url: str) -> StubResponse:
        raise httpx.RequestError("network unavailable")

    monkeypatch.setattr(adapter._client, "get", raise_request_error)

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"


def test_fetch_skips_malformed_job_without_dropping_board(
    adapter: GreenhouseAdapter,
    fixture_jobs: list[dict],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    valid_jobs = fixture_jobs[:2]
    malformed_job = dict(valid_jobs[0])
    del malformed_job["absolute_url"]

    def fake_get(_url: str) -> StubResponse:
        return StubResponse({"jobs": [valid_jobs[0], malformed_job, valid_jobs[1]]})

    monkeypatch.setattr(adapter._client, "get", fake_get)
    caplog.set_level("WARNING")

    raw_listings = adapter.fetch()

    assert adapter.health() == "ok"
    assert [listing.external_id for listing in raw_listings] == [
        str(valid_jobs[0]["id"]),
        str(valid_jobs[1]["id"]),
    ]
    assert "skipping malformed greenhouse listing" in caplog.text


def test_parse_internship_job(adapter: GreenhouseAdapter, fixture_jobs: list[dict]) -> None:
    job = next(j for j in fixture_jobs if "Intern" in j["title"])
    normalized = adapter.parse(_raw_listing_for(job))

    assert normalized.title == job["title"]
    assert normalized.company_name == "Cloudflare"
    assert normalized.category == "internship"
    assert normalized.apply_url == job["absolute_url"]
    assert normalized.external_id == str(job["id"])
    assert normalized.deadline is None
    assert normalized.deadline_confidence == "unknown"


def test_parse_non_internship_job(adapter: GreenhouseAdapter, fixture_jobs: list[dict]) -> None:
    job = next(j for j in fixture_jobs if "Intern" not in j["title"])
    normalized = adapter.parse(_raw_listing_for(job))

    assert normalized.category == "job"


def test_parse_strips_html_and_recovers_double_encoded_entities(
    adapter: GreenhouseAdapter, fixture_jobs: list[dict]
) -> None:
    job = fixture_jobs[0]
    normalized = adapter.parse(_raw_listing_for(job))

    # The real fixture's `content` field is HTML-entity-encoded HTML
    # (literal "&lt;div&gt;..." in the raw payload) - confirmed by inspecting
    # the actual captured response, not assumed.
    assert "&lt;" not in normalized.description_raw
    assert "<div" not in normalized.description_raw
    assert len(normalized.description_raw) > 50


def test_parse_is_remote_false_for_in_office_and_distributed(
    adapter: GreenhouseAdapter, fixture_jobs: list[dict]
) -> None:
    for job in fixture_jobs:
        normalized = adapter.parse(_raw_listing_for(job))
        assert normalized.is_remote is False


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Communications Intern, LATAM", "internship"),
        ("Legal Intern, Brazil", "internship"),
        ("Brex Internship Program", "internship"),
        ("Software Engineering Intern", "internship"),
        ("PhD Fall Machine Learning Intern", "internship"),
        ("Summer Co-op, Platform Engineering", "internship"),
        ("Trainee Solutions Engineer", "internship"),
        # Regression cases: "intern" is a PREFIX of these words but must NOT match.
        ("Internal Audit Lead, Stablecoins", "job"),
        ("International Strategic Finance, London", "job"),
        ("Senior Manager, International Operations", "job"),
        ("Head of SOX and Internal Controls", "job"),
        ("Account Executive, SLED (Austin)", "job"),
    ],
)
def test_classify_category_word_boundary_safety(title: str, expected: str) -> None:
    assert classify_category(title) == expected
