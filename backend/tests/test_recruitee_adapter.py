from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from crawlers.common import content_hash
from crawlers.recruitee import RecruiteeAdapter
from pipeline.normalize import classify_category

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "recruitee_sample.json"


class StubClient:
    def __init__(
        self,
        response: httpx.Response | None = None,
        error: httpx.RequestError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _sample_payload() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _response(status_code: int, payload: dict[str, Any] | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://sendcloud.recruitee.com/api/offers/")
    return httpx.Response(status_code, json=payload or {}, request=request)


def test_fetch_filters_unpublished_and_maps_raw_listings() -> None:
    payload = _sample_payload()
    adapter = RecruiteeAdapter("sendcloud", "Sendcloud")
    adapter.client = StubClient(_response(200, payload))

    listings = adapter.fetch()

    assert adapter.health() == "ok"
    assert adapter.client.urls == ["https://sendcloud.recruitee.com/api/offers/"]
    assert [listing.external_id for listing in listings] == ["1001", "1002"]
    assert all(listing.source_slug == "recruitee" for listing in listings)
    assert listings[0].source_url == ("https://sendcloud.recruitee.com/o/backend-engineer-intern")
    assert listings[0].content_hash == content_hash(payload["offers"][0])
    assert listings[0].raw_payload == payload["offers"][0]


def test_parse_maps_recruitee_offer_fields() -> None:
    payload = _sample_payload()
    adapter = RecruiteeAdapter("sendcloud", "Sendcloud")
    adapter.client = StubClient(_response(200, payload))
    listings = adapter.fetch()

    parsed = adapter.parse(listings[0])

    assert parsed.source_slug == "recruitee"
    assert parsed.external_id == "1001"
    assert parsed.title == "Backend Engineer Intern"
    assert parsed.company_name == "Sendcloud"
    assert parsed.apply_url == ("https://sendcloud.recruitee.com/o/backend-engineer-intern/c/new")
    assert parsed.source_url == ("https://sendcloud.recruitee.com/o/backend-engineer-intern")
    assert parsed.is_remote is True
    assert parsed.location == "Amsterdam, North Holland, Netherlands"
    assert parsed.category == classify_category("Backend Engineer Intern")
    assert parsed.description_raw == "Build carrier integrations for shipping teams."
    assert parsed.posted_at == datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
    assert parsed.deadline is None
    assert parsed.deadline_confidence == "unknown"


def test_parse_uses_position_and_false_remote() -> None:
    payload = _sample_payload()
    adapter = RecruiteeAdapter("sendcloud", "Sendcloud")
    adapter.client = StubClient(_response(200, payload))
    listings = adapter.fetch()

    parsed = adapter.parse(listings[1])

    assert parsed.title == "Customer Success Graduate"
    assert parsed.is_remote is False
    assert parsed.location == "Utrecht, Netherlands"
    assert parsed.category == classify_category("Customer Success Graduate")
    assert parsed.posted_at == datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    assert parsed.deadline_confidence == "unknown"


def test_fetch_404_marks_broken_without_raising() -> None:
    adapter = RecruiteeAdapter("sendcloud", "Sendcloud")
    adapter.client = StubClient(_response(404))

    listings = adapter.fetch()

    assert adapter.health() == "broken"
    assert listings == []


def test_fetch_request_error_marks_degraded_without_raising() -> None:
    request = httpx.Request("GET", "https://sendcloud.recruitee.com/api/offers/")
    adapter = RecruiteeAdapter("sendcloud", "Sendcloud")
    adapter.client = StubClient(error=httpx.RequestError("timeout", request=request))

    listings = adapter.fetch()

    assert adapter.health() == "degraded"
    assert listings == []
