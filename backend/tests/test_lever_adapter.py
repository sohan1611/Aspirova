"""Unit tests for LeverAdapter.parse() against a captured real payload
(tests/fixtures/lever_weride_sample.json - 1 real internship + 1 real
non-internship job, fetched live from api.lever.co/v0/postings/weride).
No network access required - fetch() is not exercised here.
"""

import json
from pathlib import Path

import pytest

from core.adapters import RawListing
from crawlers.common import content_hash
from crawlers.lever import LeverAdapter
from pipeline.normalize import classify_category

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lever_weride_sample.json"


def _load_fixture_postings() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(posting: dict) -> RawListing:
    return RawListing(
        source_slug="lever",
        external_id=posting["id"],
        source_url=posting["hostedUrl"],
        content_hash=content_hash(posting),
        raw_payload=posting,
    )


@pytest.fixture
def adapter() -> LeverAdapter:
    return LeverAdapter(board_token="weride", company_name="WeRide")


@pytest.fixture
def fixture_postings() -> list[dict]:
    return _load_fixture_postings()


def test_adapter_identity(adapter: LeverAdapter) -> None:
    assert adapter.source_slug == "lever"
    assert adapter.requires_browser is False


def test_health_defaults_to_ok_before_any_fetch(adapter: LeverAdapter) -> None:
    assert adapter.health() == "ok"


def test_parse_internship_job(adapter: LeverAdapter, fixture_postings: list[dict]) -> None:
    posting = next(p for p in fixture_postings if "intern" in p["text"].lower())
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.title == posting["text"]
    assert normalized.company_name == "WeRide"
    assert normalized.category == "internship"
    assert normalized.apply_url == posting["hostedUrl"]
    assert normalized.external_id == posting["id"]
    assert normalized.deadline is None
    assert normalized.deadline_confidence == "unknown"


def test_parse_non_internship_job(adapter: LeverAdapter, fixture_postings: list[dict]) -> None:
    posting = next(p for p in fixture_postings if "intern" not in p["text"].lower())
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.category == "job"


def test_parse_uses_plain_text_description_directly(
    adapter: LeverAdapter, fixture_postings: list[dict]
) -> None:
    """Unlike Greenhouse, Lever provides descriptionPlain directly - no
    HTML-entity unescaping/tag-stripping needed."""
    posting = fixture_postings[0]
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.description_raw == posting["descriptionPlain"]
    assert "<" not in normalized.description_raw


def test_parse_location_comes_from_categories(
    adapter: LeverAdapter, fixture_postings: list[dict]
) -> None:
    posting = fixture_postings[0]
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.location == posting["categories"]["location"]


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Software Engineering Intern", "internship"),
        ("2026 Summer Intern - PhD", "internship"),
        ("Internal Audit Lead", "job"),
        ("International Strategic Finance", "job"),
    ],
)
def test_classify_category_word_boundary_safety(title: str, expected: str) -> None:
    assert classify_category(title) == expected
