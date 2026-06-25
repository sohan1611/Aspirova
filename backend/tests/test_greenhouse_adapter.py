"""Unit tests for GreenhouseAdapter.parse() against a captured real payload
(tests/fixtures/greenhouse_cloudflare_sample.json - 2 real internships +
1 real non-internship job, fetched live from boards-api.greenhouse.io).
No network access required - fetch() is not exercised here.
"""

import json
from pathlib import Path

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
