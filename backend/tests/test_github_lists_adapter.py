"""Recorded public list samples; HTTP is always intercepted."""

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from core.summarise import summarise_description
from crawlers import github_lists as github
from crawlers.runner import AGGREGATOR_ADAPTERS, _coverage_from_adapter
from pipeline.normalize import NEW_GRAD_TITLE_PATTERN
from scripts.seed_companies import _AGGREGATOR_SOURCES

FIXTURE = Path(__file__).parent / "fixtures" / "github_lists_sample.json"


@pytest.fixture
def samples() -> dict[str, list[dict]]:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    return {entry["repo"]: entry["records"] for entry in captured}


def _inventory_rows(records, count=github.MIN_LIST_RECORDS):
    # Expand compact captures with explicitly inactive fixture-derived rows.
    captured = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    closed = captured[0]["records"][-1]
    assert closed["active"] is False
    return records + [
        closed | {"id": f"fixture-closed-{index}"} for index in range(max(count - len(records), 0))
    ]


def _adapter(
    monkeypatch,
    samples,
    *,
    failed_repo=None,
    invalid_repo=None,
    record_count=github.MIN_LIST_RECORDS,
):
    adapter = github.GithubListsAdapter()

    def respond(request):
        repo = "/".join(request.url.path.strip("/").split("/")[:2])
        if repo == failed_repo:
            return httpx.Response(404)
        if repo == invalid_repo:
            return httpx.Response(200, json={"unexpected": []})
        return httpx.Response(200, json=_inventory_rows(samples[repo], record_count))

    adapter._client.close()
    adapter._client = httpx.Client(
        transport=httpx.MockTransport(respond), headers={"User-Agent": github.USER_AGENT}
    )
    monkeypatch.setattr(github, "sleep", lambda _delay: None)
    return adapter


def _record(samples, repo_index=0):
    return copy.deepcopy(samples[github.LIST_REPOS[repo_index][0]][0])


def test_recorded_lists_metadata_and_employer_links(monkeypatch, samples):
    adapter = _adapter(monkeypatch, samples)
    raw = adapter.fetch()
    assert raw
    parsed = [adapter.parse(item) for item in raw]
    assert adapter.health() == "ok"
    assert adapter.coverage()["mode"] == "full_list"
    assert adapter.coverage()["status"] == "complete"
    assert adapter.coverage()["details"]["skipped_ats_hosted"] > 0
    for listing in parsed:
        assert listing.deadline is None
        assert listing.deadline_confidence == "unknown"
        assert listing.meta["summary_source"] == "extracted"
        assert listing.meta["attribution"] == github.ATTRIBUTION
        assert listing.meta["list_repo"] in samples
        assert (
            "terms" in listing.meta and "sponsorship" in listing.meta and "degrees" in listing.meta
        )
        assert listing.source_url == listing.apply_url
        assert "simplify.jobs" not in listing.apply_url
        assert listing.company_domain != "simplify.jobs"
        assert summarise_description(listing.description_raw, title=listing.title)
        if listing.category == "job":
            assert re.search(NEW_GRAD_TITLE_PATTERN, listing.title, re.IGNORECASE)
    assert AGGREGATOR_ADAPTERS["github_lists"] is github.GithubListsAdapter
    assert _AGGREGATOR_SOURCES["github_lists"][1] == github.ATTRIBUTION


@pytest.mark.parametrize("failure", ["missing", "invalid"])
def test_one_failed_file_is_partial(monkeypatch, samples, failure):
    repo = github.LIST_REPOS[-1][0]
    adapter = _adapter(
        monkeypatch, samples, **{("failed_repo" if failure == "missing" else "invalid_repo"): repo}
    )
    assert adapter.fetch()
    assert adapter.health() == "degraded"
    assert adapter.coverage()["status"] == "partial"
    assert repo in adapter.coverage()["details"]["failures"]


def test_eligibility_and_cross_file_dedup_prefer_first_configured_file(monkeypatch, samples):
    first = _record(samples)
    first.update(
        url="https://careers.example.org/jobs/123?utm_source=list&req=123&source=github",
        locations=["Remote, India"],
        company_url="https://acme.example.org",
    )
    second = copy.deepcopy(first)
    second.update(id="cross-list-copy", url="https://careers.example.org/jobs/123?req=123&ref=list")
    role_duplicate = copy.deepcopy(first)
    role_duplicate.update(id="another-url", url="https://careers.example.org/another-url")
    inactive = copy.deepcopy(first) | {"active": False, "url": "https://example.org/inactive"}
    invisible = copy.deepcopy(first) | {"is_visible": False, "url": "https://example.org/invisible"}
    simplify_link = copy.deepcopy(first) | {"url": "https://simplify.jobs/p/123"}
    wrapped_link = copy.deepcopy(first) | {"url": "https://go.vansh.nyc/G"}
    samples = {
        github.LIST_REPOS[0][0]: [first, inactive, invisible, simplify_link, wrapped_link],
        github.LIST_REPOS[1][0]: [second, role_duplicate],
    }
    adapter = _adapter(monkeypatch, samples)
    raw = adapter.fetch()
    assert len(raw) == 1
    assert raw[0].source_url == "https://careers.example.org/jobs/123?req=123"
    assert raw[0].raw_payload["list_repo"] == github.LIST_REPOS[0][0]
    parsed = adapter.parse(raw[0])
    assert parsed.is_remote is True and parsed.country == "IN"
    assert parsed.company_domain == "acme.example.org"
    assert adapter.coverage()["details"]["duplicates"] == 2
    assert adapter.coverage()["details"]["skipped_invalid_or_wrapped_url"] == 2


@pytest.mark.parametrize("date_posted", [0, 1577836800, 4102444800, None, "invalid"])
def test_active_visible_records_are_ingested_regardless_of_posting_date(
    monkeypatch, samples, date_posted
):
    record = _record(samples) | {"date_posted": date_posted}
    samples = {
        repo: [record] if index == 0 else []
        for index, (repo, _category) in enumerate(github.LIST_REPOS)
    }
    adapter = _adapter(monkeypatch, samples)
    raw = adapter.fetch()
    assert len(raw) == 1
    assert raw[0].source_url == record["url"]
    parsed = adapter.parse(raw[0])
    expected = datetime.fromtimestamp(date_posted, UTC) if isinstance(date_posted, int) else None
    assert parsed.posted_at == expected
    assert adapter.coverage()["status"] == "complete"


@pytest.mark.parametrize(
    "host",
    [
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.eu.greenhouse.io",
        "jobs.lever.co",
        "jobs.ashbyhq.com",
        "apply.workable.com",
        "jobs.smartrecruiters.com",
        "acme.recruitee.com",
        "acme.wd5.myworkdayjobs.com",
    ],
)
def test_every_per_board_ats_host_is_skipped(host, monkeypatch, samples):
    record = _record(samples) | {"url": f"https://{host}/acme/job/123"}
    samples = {
        repo: [record] if index == 0 else []
        for index, (repo, _category) in enumerate(github.LIST_REPOS)
    }
    adapter = _adapter(monkeypatch, samples)
    assert adapter.fetch() == []
    assert adapter.coverage()["details"]["skipped_ats_hosted"] == 1


def test_url_canonicalization_preserves_job_query_and_ashby_form():
    assert (
        github.canonical_url(
            "https://jobs.ashbyhq.com/Acme/123/application?utm_campaign=x&source=y&gh_src=z&ref=foo&job=7#apply"
        )
        == "https://jobs.ashbyhq.com/Acme/123?job=7"
    )
    assert (
        github.canonical_url("https://acme.example/application?job=7")
        == "https://acme.example/application?job=7"
    )
    assert not github.is_board_ats_url("https://jobs.lever.co.evil.example/acme/job")
    # Wrapped links remain excluded even if another configured list contains one.
    assert github.canonical_url("https://go.vansh.nyc/G") is None


@pytest.mark.parametrize(
    "record_count,status", [(0, "partial"), (1000, "partial"), (1001, "complete")]
)
def test_complete_coverage_requires_sane_counts_in_every_file(monkeypatch, record_count, status):
    samples = {repo: [] for repo, _category in github.LIST_REPOS}
    adapter = _adapter(monkeypatch, samples, record_count=record_count)
    assert adapter.fetch() == []
    coverage = adapter.coverage()
    assert coverage["status"] == status
    assert coverage["details"]["record_counts"] == {repo: record_count for repo in samples}
    assert bool(coverage["details"]["failures"]) is (status == "partial")
    assert adapter.health() == ("ok" if status == "complete" else "degraded")


def test_one_undersized_file_makes_otherwise_successful_fetch_partial(monkeypatch, samples):
    first_repo = github.LIST_REPOS[0][0]
    samples[first_repo] = _inventory_rows(samples[first_repo])
    adapter = _adapter(monkeypatch, samples, record_count=1000)
    assert adapter.fetch()
    coverage = adapter.coverage()
    assert coverage["status"] == "partial"
    assert coverage["details"]["record_counts"][first_repo] == 1001
    assert list(coverage["details"]["failures"]) == [github.LIST_REPOS[1][0]]


def test_configured_files_are_simplify_only_and_fetcher_supports_one_file(monkeypatch, samples):
    assert len(github.LIST_REPOS) == 2
    assert all(repo.startswith("SimplifyJobs/") for repo, _category in github.LIST_REPOS)
    monkeypatch.setattr(github, "LIST_REPOS", github.LIST_REPOS[:1])
    adapter = _adapter(monkeypatch, samples)
    assert adapter.fetch()
    assert adapter.coverage()["status"] == "complete"
    assert adapter.coverage()["details"]["fetched_repos"] == [github.LIST_REPOS[0][0]]


def test_retry_after_is_honored(monkeypatch, samples):
    waits = []
    requests = []
    adapter = github.GithubListsAdapter()

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        repo = "/".join(request.url.path.strip("/").split("/")[:2])
        return httpx.Response(200, json=_inventory_rows(samples[repo]))

    adapter._client.close()
    adapter._client = httpx.Client(
        transport=httpx.MockTransport(respond), headers={"User-Agent": github.USER_AGENT}
    )
    monkeypatch.setattr(github, "sleep", waits.append)
    assert adapter.fetch()
    assert 3.0 in waits and waits.count(0.5) == len(github.LIST_REPOS) + 1
    assert adapter.coverage()["status"] == "complete"
    assert all(request.headers["User-Agent"] == github.USER_AGENT for request in requests)


def test_runner_soft_stop_overrides_complete_adapter_coverage(monkeypatch, samples):
    adapter = _adapter(monkeypatch, samples)
    listings = adapter.fetch()
    coverage = _coverage_from_adapter(
        adapter, "github_lists", len(listings), health="ok", stopped_early=True
    )
    assert coverage["status"] == "partial"
