"""Unit tests for SmartRecruitersAdapter against captured real payloads."""

import json
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.smartrecruiters import (
    SmartRecruitersAdapter,
    _content_hash,
    _extract_text,
)
from crawlers.runner import _board_fingerprint
from pipeline.normalize import classify_category

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smartrecruiters_sample.json"


def _load_fixture_postings() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["postings"]


def _raw_listing_for(posting: dict) -> RawListing:
    list_posting = _list_posting(posting)
    return RawListing(
        source_slug="smartrecruiters",
        external_id=str(posting["id"]),
        source_url=posting.get("postingUrl") or posting["applyUrl"],
        content_hash=_listing_content_hash(list_posting),
        raw_payload=list_posting,
    )


def _list_posting(posting: dict) -> dict:
    return {key: value for key, value in posting.items() if key != "jobAd"}


def _listing_content_hash(posting: dict) -> str:
    return _content_hash(
        {
            "id": posting.get("id"),
            "name": posting.get("name"),
            "releasedDate": posting.get("releasedDate"),
            "location": posting.get("location"),
        }
    )


def make_client(
    postings: list[dict], *, detail_status: int = 200
) -> tuple[httpx.Client, dict[str, int]]:
    by_id = {str(posting["id"]): posting for posting in postings}
    list_postings = [_list_posting(posting) for posting in postings]
    calls = {"list": 0, "detail": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/postings"):
            calls["list"] += 1
            return httpx.Response(
                200,
                json={"content": list_postings, "totalFound": len(list_postings)},
            )

        calls["detail"] += 1
        posting_id = path.rsplit("/", 1)[-1]
        if detail_status != 200:
            return httpx.Response(detail_status, json={})
        return httpx.Response(200, json=by_id[posting_id])

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def _adapter_with_client(
    board_token: str,
    company_name: str,
    postings: list[dict],
    *,
    detail_status: int = 200,
) -> tuple[SmartRecruitersAdapter, dict[str, int]]:
    adapter = SmartRecruitersAdapter(board_token=board_token, company_name=company_name)
    client, calls = make_client(postings, detail_status=detail_status)
    adapter._client.close()
    adapter._client = client
    return adapter, calls


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
    adapter, _ = _adapter_with_client("Wise", "Wise", fixture_postings)
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
    adapter, _ = _adapter_with_client("Wise", "Wise", fixture_postings)
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
    adapter, _ = _adapter_with_client(identifier, company_name, fixture_postings)
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.is_remote is expected_remote


def test_parse_category_uses_shared_classifier(fixture_postings: list[dict]) -> None:
    for posting in fixture_postings:
        adapter, _ = _adapter_with_client(
            posting["company"]["identifier"],
            posting["company"]["name"],
            fixture_postings,
        )
        normalized = adapter.parse(_raw_listing_for(posting))

        assert normalized.category == classify_category(posting["name"])


def test_parse_cleans_comma_segments_from_location(
    fixture_postings: list[dict],
) -> None:
    for posting in fixture_postings:
        adapter, _ = _adapter_with_client(
            posting["company"]["identifier"],
            posting["company"]["name"],
            fixture_postings,
        )
        normalized = adapter.parse(_raw_listing_for(posting))

        assert normalized.location
        assert ", ," not in normalized.location
        assert all(part.strip() for part in normalized.location.split(","))


def test_parse_released_date_to_timezone_aware_datetime(
    fixture_postings: list[dict],
) -> None:
    posting = _posting_for(fixture_postings, "WesternDigital")
    adapter, _ = _adapter_with_client("WesternDigital", "Western Digital", fixture_postings)
    normalized = adapter.parse(_raw_listing_for(posting))

    assert normalized.posted_at is not None
    assert normalized.posted_at.tzinfo is not None
    assert normalized.posted_at.utcoffset() is not None


def test_fetch_lists_without_any_detail_calls(fixture_postings: list[dict]) -> None:
    adapter, calls = _adapter_with_client("Wise", "Wise", fixture_postings)

    listings = adapter.fetch()

    assert len(listings) == len(fixture_postings)
    assert calls == {"list": 1, "detail": 0}
    assert [listing.content_hash for listing in listings] == [
        _listing_content_hash(posting) for posting in fixture_postings
    ]
    assert all("jobAd" not in listing.raw_payload for listing in listings)


def test_fetch_content_hash_ignores_non_identity_list_fields(
    fixture_postings: list[dict],
) -> None:
    original = fixture_postings[0]
    changed = json.loads(json.dumps(original))
    # These are real LIST fields outside the four-field identity hash set.
    changed["refNumber"] = "REF-CHANGED-99999"
    changed["uuid"] = "00000000-0000-0000-0000-000000000000"
    changed["applyUrl"] = "https://jobs.smartrecruiters.com/Wise/changed?oga=true"
    original_adapter, _ = _adapter_with_client("Wise", "Wise", [original])
    changed_adapter, _ = _adapter_with_client("Wise", "Wise", [changed])

    original_hash = original_adapter.fetch()[0].content_hash
    changed_hash = changed_adapter.fetch()[0].content_hash

    assert original_hash == changed_hash


def test_unchanged_board_recrawl_has_stable_fingerprint_and_zero_detail_calls(
    fixture_postings: list[dict],
) -> None:
    adapter, calls = _adapter_with_client("Wise", "Wise", fixture_postings)

    first = _board_fingerprint(adapter.fetch())
    # A matching fingerprint lets crawl_company_board skip parse()/DETAIL work.
    second = _board_fingerprint(adapter.fetch())

    assert first == second
    assert calls["detail"] == 0
    assert calls["list"] == 2


def test_fetch_content_hash_changes_on_list_field_change(
    fixture_postings: list[dict],
) -> None:
    original = fixture_postings[0]
    changed_name = json.loads(json.dumps(original))
    changed_name["name"] = f'{original["name"]} (updated)'
    original_adapter, _ = _adapter_with_client("Wise", "Wise", [original])
    changed_adapter, _ = _adapter_with_client("Wise", "Wise", [changed_name])

    original_hash = original_adapter.fetch()[0].content_hash
    changed_hash = changed_adapter.fetch()[0].content_hash

    assert original_hash != changed_hash


def test_parse_makes_exactly_one_detail_call(fixture_postings: list[dict]) -> None:
    posting = _posting_for(fixture_postings, "Wise")
    adapter, calls = _adapter_with_client("Wise", "Wise", fixture_postings)

    normalized = adapter.parse(_raw_listing_for(posting))

    assert calls == {"list": 0, "detail": 1}
    assert normalized.description_raw


def test_parse_raises_when_detail_fetch_fails(fixture_postings: list[dict]) -> None:
    posting = _posting_for(fixture_postings, "Wise")
    adapter, calls = _adapter_with_client("Wise", "Wise", fixture_postings, detail_status=500)

    with pytest.raises(RuntimeError, match="detail fetch failed"):
        adapter.parse(_raw_listing_for(posting))

    assert calls == {"list": 0, "detail": 1}
