from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from crawlers.common import content_hash
from crawlers.workable import WorkableAdapter
from pipeline.normalize import classify_category

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "workable_sample.json"


class StubResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        *,
        json_error: bool = False,
    ) -> None:
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error:
            raise ValueError("invalid JSON")
        return self._payload


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fetch_and_parse_workable_fixture(monkeypatch) -> None:
    payload = _load_fixture()
    seen_urls: list[str] = []

    def fake_get(
        _client: httpx.Client,
        url: str,
        **kwargs: bool,
    ) -> StubResponse:
        assert kwargs == {"follow_redirects": True}
        seen_urls.append(url)
        return StubResponse(200, payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    adapter = WorkableAdapter("huggingface", "Hugging Face")
    raw_listings = adapter.fetch()

    assert adapter.health() == "ok"
    assert seen_urls == [
        "https://apply.workable.com/api/v1/widget/accounts/" "huggingface?details=true"
    ]
    assert len(raw_listings) == 3
    assert raw_listings[0].external_id == "A1B2C3D4"
    assert raw_listings[0].source_url == "https://apply.workable.com/huggingface/j/A1B2C3D4/"
    assert raw_listings[0].content_hash == content_hash(payload["jobs"][0])

    remote_listing = adapter.parse(raw_listings[0])
    assert remote_listing.title == "Machine Learning Engineer, Inference"
    assert remote_listing.company_name == "Hugging Face"
    assert remote_listing.apply_url == "https://apply.workable.com/j/A1B2C3D4/apply"
    assert remote_listing.is_remote is True
    assert remote_listing.location == "New York, New York, United States"
    assert remote_listing.category == classify_category(remote_listing.title)
    assert "Build production inference systems" in remote_listing.description_raw
    assert remote_listing.posted_at == datetime(2026, 5, 29, tzinfo=UTC)
    assert remote_listing.deadline is None
    assert remote_listing.deadline_confidence == "unknown"

    onsite_listing = adapter.parse(raw_listings[1])
    assert onsite_listing.title == "Product Designer"
    assert onsite_listing.is_remote is False
    assert onsite_listing.location == "Paris, France"
    assert onsite_listing.posted_at == datetime(2026, 6, 3, tzinfo=UTC)

    fallback_location_listing = adapter.parse(raw_listings[2])
    assert fallback_location_listing.location == "San Francisco, California, United States"


def test_fetch_marks_broken_for_error_object_without_jobs(monkeypatch) -> None:
    adapter = WorkableAdapter("missing-board", "Missing Board")
    monkeypatch.setattr(
        adapter.client,
        "get",
        lambda _url, **_kwargs: StubResponse(200, {"error": "unknown"}),
    )

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


def test_fetch_accepts_empty_jobs_container(monkeypatch) -> None:
    adapter = WorkableAdapter("huggingface", "Hugging Face")
    monkeypatch.setattr(
        adapter.client,
        "get",
        lambda _url, **_kwargs: StubResponse(200, {"jobs": []}),
    )

    assert adapter.fetch() == []
    assert adapter.health() == "ok"


def test_fetch_marks_broken_for_invalid_json(monkeypatch) -> None:
    adapter = WorkableAdapter("huggingface", "Hugging Face")
    monkeypatch.setattr(
        adapter.client,
        "get",
        lambda _url, **_kwargs: StubResponse(200, json_error=True),
    )

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


def test_fetch_marks_broken_on_404(monkeypatch) -> None:
    def fake_get(
        _client: httpx.Client,
        _url: str,
        **kwargs: bool,
    ) -> StubResponse:
        assert kwargs == {"follow_redirects": True}
        return StubResponse(404)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    adapter = WorkableAdapter("missing-board", "Missing Board")

    assert adapter.fetch() == []
    assert adapter.health() == "broken"


def test_fetch_marks_degraded_on_non_200(monkeypatch) -> None:
    adapter = WorkableAdapter("huggingface", "Hugging Face")
    monkeypatch.setattr(
        adapter.client,
        "get",
        lambda _url, **_kwargs: StubResponse(500),
    )

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"


def test_fetch_marks_degraded_on_request_error(monkeypatch) -> None:
    def fake_get(
        _client: httpx.Client,
        _url: str,
        **kwargs: bool,
    ) -> StubResponse:
        assert kwargs == {"follow_redirects": True}
        raise httpx.RequestError("network unavailable")

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    adapter = WorkableAdapter("huggingface", "Hugging Face")

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"
