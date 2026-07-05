"""Unit tests for RemoteOkAdapter.parse() against a captured real payload
(tests/fixtures/remoteok_sample.json - 3 real listings fetched live from
remoteok.com/api, including one with an HTML-entity-encoded company name).
No network access required - fetch() is not exercised here.
"""

import json
from pathlib import Path

import pytest

from core.adapters import RawListing
from crawlers.common import content_hash
from crawlers.remoteok import RemoteOkAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "remoteok_sample.json"


def _load_fixture_jobs() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(job: dict) -> RawListing:
    return RawListing(
        source_slug="remoteok",
        external_id=str(job["id"]),
        source_url=job.get("url") or job["apply_url"],
        content_hash=content_hash(job),
        raw_payload=job,
    )


@pytest.fixture
def adapter() -> RemoteOkAdapter:
    return RemoteOkAdapter()


@pytest.fixture
def fixture_jobs() -> list[dict]:
    return _load_fixture_jobs()


def test_adapter_identity(adapter: RemoteOkAdapter) -> None:
    assert adapter.source_slug == "remoteok"
    assert adapter.requires_browser is False


def test_health_defaults_to_ok_before_any_fetch(adapter: RemoteOkAdapter) -> None:
    assert adapter.health() == "ok"


def test_parse_all_listings_are_remote(adapter: RemoteOkAdapter, fixture_jobs: list[dict]) -> None:
    for job in fixture_jobs:
        normalized = adapter.parse(_raw_listing_for(job))
        assert normalized.is_remote is True


def test_parse_unescapes_html_entities_in_company_name(
    adapter: RemoteOkAdapter, fixture_jobs: list[dict]
) -> None:
    """Real production case: RemoteOK's `company` field is HTML-entity
    encoded (e.g. "RG&amp;T Solutions"), same class of issue as
    Greenhouse's double-encoded `content` field."""
    job = next(j for j in fixture_jobs if "&amp;" in j["company"])
    normalized = adapter.parse(_raw_listing_for(job))

    assert "&amp;" not in normalized.company_name
    assert "&" in normalized.company_name  # the real ampersand survives unescaping


def test_parse_strips_html_from_description(
    adapter: RemoteOkAdapter, fixture_jobs: list[dict]
) -> None:
    job = fixture_jobs[0]
    normalized = adapter.parse(_raw_listing_for(job))

    assert "<" not in normalized.description_raw
    assert len(normalized.description_raw) > 20


def test_parse_apply_url_is_the_remoteok_hosted_page_not_aspirova(
    adapter: RemoteOkAdapter, fixture_jobs: list[dict]
) -> None:
    """Doc 01 sec 7 R1 / Doc 04 sec 10: link out, never mirror - and
    RemoteOK's own API terms explicitly require linking back to them."""
    job = fixture_jobs[0]
    normalized = adapter.parse(_raw_listing_for(job))

    assert "remoteok.com" in normalized.apply_url.lower()
    assert "aspirova" not in normalized.apply_url.lower()


def test_parse_external_id_and_titles_are_populated(
    adapter: RemoteOkAdapter, fixture_jobs: list[dict]
) -> None:
    for job in fixture_jobs:
        normalized = adapter.parse(_raw_listing_for(job))
        assert normalized.external_id == str(job["id"])
        assert normalized.title
        assert normalized.company_name
