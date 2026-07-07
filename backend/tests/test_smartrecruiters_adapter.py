"""Unit tests for SmartRecruitersAdapter.parse() against captured real payloads.
No network access required - fetch() is not exercised here.
"""

import json
from pathlib import Path

import pytest

from core.adapters import RawListing
from crawlers.smartrecruiters import (
    SmartRecruitersAdapter,
    _content_hash,
    _extract_text,
)
from pipeline.normalize import classify_category

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smartrecruiters_sample.json"


def _load_fixture_postings() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["postings"]


def _raw_listing_for(posting: dict) -> RawListing:
    return RawListing(
        source_slug="smartrecruiters",
        external_id=str(posting["id"]),
        source_url=posting.get("postingUrl") or posting["applyUrl"],
        content_hash=_content_hash(posting),
        raw_payload=posting,
    )


def _posting_for(postings: list[dict], identifier: str) -> dict:
    return next(posting for posting in postings if posting["company"]["identifier"] == identifier)


def _section_texts(posting: dict) -> list[str]:
    sections = posting["jobAd"]["sections"]
    names = [
        "companyDescription",
        "jobDescription",
        "qualifications",
        "additionalInformation",
    ]
    return [
        text
        for text in (_extract_text(sections[name].get("text")).strip() for name in names)
        if text
    ]


@pytest.fixture
def fixture_postings() -> list[dict]:
    return _load_fixture_postings()


def test_adapter_identity() -> None:
    adapter = SmartRecruitersAdapter(board_token="Wise", company_name="Wise")

    assert adapter.source_slug == "smartrecruiters"
    assert adapter.requires_browser is False


def test_health_defaults_to_ok_before_any_fetch() -> None:
    adapter = SmartRecruitersAdapter(board_token="Wise", company_name="Wise")

    assert adapter.health() == "ok"


def test_parse_maps_identity_fields(fixture_postings: list[dict]) -> None:
    posting = _posting_for(fixture_postings, "Wise")
    adapter = SmartRecruitersAdapter(board_token="Wise", company_name="Wise")
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.source_slug == "smartrecruiters"
    assert normalized.title == posting["name"]
    assert normalized.company_name == "Wise"
    assert normalized.apply_url == posting["postingUrl"]
    assert normalized.external_id == str(posting["id"])
    assert normalized.deadline is None
    assert normalized.deadline_confidence == "unknown"


def test_parse_strips_html_and_joins_multiple_sections(
    fixture_postings: list[dict],
) -> None:
    posting = _posting_for(fixture_postings, "Wise")
    adapter = SmartRecruitersAdapter(board_token="Wise", company_name="Wise")
    normalized = adapter.parse(_raw_listing_for(posting))
    section_texts = _section_texts(posting)

    assert normalized.description_raw
    assert "<" not in normalized.description_raw
    assert "&lt;" not in normalized.description_raw
    assert len(section_texts) >= 2
    assert section_texts[0][:40] in normalized.description_raw
    assert section_texts[1][:40] in normalized.description_raw


@pytest.mark.parametrize(
    ("identifier", "company_name", "expected_remote"),
    [
        ("Wise", "Wise", False),
        ("WesternDigital", "Western Digital", True),
        ("Visa", "Visa", False),
    ],
)
def test_parse_remote_flag(
    fixture_postings: list[dict],
    identifier: str,
    company_name: str,
    expected_remote: bool,
) -> None:
    posting = _posting_for(fixture_postings, identifier)
    adapter = SmartRecruitersAdapter(
        board_token=identifier,
        company_name=company_name,
    )
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.is_remote is expected_remote


def test_parse_category_uses_shared_classifier(fixture_postings: list[dict]) -> None:
    for posting in fixture_postings:
        adapter = SmartRecruitersAdapter(
            board_token=posting["company"]["identifier"],
            company_name=posting["company"]["name"],
        )
        normalized = adapter.parse(_raw_listing_for(posting))

        assert normalized.category == classify_category(posting["name"])


def test_parse_cleans_comma_segments_from_location(
    fixture_postings: list[dict],
) -> None:
    for posting in fixture_postings:
        adapter = SmartRecruitersAdapter(
            board_token=posting["company"]["identifier"],
            company_name=posting["company"]["name"],
        )
        normalized = adapter.parse(_raw_listing_for(posting))

        assert normalized.location
        assert ", ," not in normalized.location
        assert all(part.strip() for part in normalized.location.split(","))


def test_parse_released_date_to_timezone_aware_datetime(
    fixture_postings: list[dict],
) -> None:
    posting = _posting_for(fixture_postings, "WesternDigital")
    adapter = SmartRecruitersAdapter(
        board_token="WesternDigital",
        company_name="Western Digital",
    )
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.posted_at is not None
    assert normalized.posted_at.tzinfo is not None
    assert normalized.posted_at.utcoffset() is not None
