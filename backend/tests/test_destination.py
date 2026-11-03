"""Outbound destination classification, including live and spoofed hosts."""

from datetime import UTC, datetime

import pytest

from api.schemas import OpportunityDetail, OpportunityListItem
from core import models
from core.destination import ApplyDestination, classify_destination


@pytest.mark.parametrize(
    "host,kind,label",
    [
        ("jobs.smartrecruiters.com", "ats", "SmartRecruiters"),
        ("arbeitnow.com", "job_board", "Arbeitnow"),
        ("arbeitnow.ch", "job_board", "Arbeitnow"),
        ("arbeitnow.fr", "job_board", "Arbeitnow"),
        ("arbeitnow.co.uk", "job_board", "Arbeitnow"),
        ("job-boards.greenhouse.io", "ats", "Greenhouse"),
        ("block.xyz", "company", None),
        ("jobs.ashbyhq.com", "ats", "Ashby"),
        ("himalayas.app", "job_board", "Himalayas"),
        ("unstop.com", "event_platform", "Unstop"),
        ("www.amazon.jobs", "company", None),
        ("tum.devfolio.co", "event_platform", "Devfolio"),
        ("remoteOK.com", "job_board", "RemoteOK"),
        ("jobs.lever.co", "ats", "Lever"),
        ("uxperience-f26.devpost.com", "event_platform", "Devpost"),
        ("satsure.keka.com", "ats", "Keka"),
        ("remoteok.io", "job_board", "RemoteOK"),
        ("jobicy.com", "job_board", "Jobicy"),
        ("challenges.hackerearth.com", "event_platform", "HackerEarth"),
        ("acme.recruitee.com", "ats", "Recruitee"),
        ("apply.workable.com", "ats", "Workable"),
        ("acme.myworkdayjobs.com", "ats", "Workday"),
        ("unknown.example", "unverified", None),
    ],
)
def test_live_and_supported_hosts(host: str, kind: str, label: str | None) -> None:
    result = classify_destination(f"https://{host}/listing", "block.xyz")
    assert result.kind == kind
    assert result.host == host.lower().removeprefix("www.")
    assert result.label == label


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "not a URL",
        "example.com/job",
        "//lever.co/job",
        "ftp://lever.co/job",
        "javascript:alert(1)",
        "https://",
        "https://[invalid",
        "https://lever.co:bad/job",
        "https://bad host/job",
        "https://lever.co\\evil.com/job",
    ],
)
def test_missing_or_invalid_url(url: str | None) -> None:
    assert classify_destination(url, "lever.co") == ApplyDestination("unverified")


@pytest.mark.parametrize(
    "host",
    [
        "notlever.co",
        "lever.co.evil.com",
        "evilgreenhouse.io",
        "ashbyhq.com.evil.com",
        "notamazon.jobs",
        "amazon.jobs.evil.com",
        "arbeitnow.evil.com",
        "arbeitnow.com.evil.com",
        "notarbeitnow.com",
        "arbeitnow.github.io",
        "himalayas.app.evil.com",
        "notdevpost.com",
        "unstop.com.evil.com",
    ],
)
def test_suffix_spoofs_are_unverified(host: str) -> None:
    assert classify_destination(f"https://{host}/job", None) == ApplyDestination(
        "unverified", host.lower().removeprefix("www.")
    )


@pytest.mark.parametrize("domain", ["www.BLOCK.xyz", "BLOCK.xyz", "https://www.block.xyz/"])
def test_company_domain_is_normalized_and_matches_subdomains(domain: str) -> None:
    assert classify_destination("https://careers.block.xyz/job", domain) == ApplyDestination(
        "company", "careers.block.xyz"
    )


@pytest.mark.parametrize("host", ["notblock.xyz", "block.xyz.evil.com"])
def test_company_domain_uses_dot_boundaries(host: str) -> None:
    assert classify_destination(f"https://{host}/job", "block.xyz").kind == "unverified"


def test_company_match_has_priority_over_ats() -> None:
    assert classify_destination("https://jobs.lever.co/lever", "lever.co") == ApplyDestination(
        "company", "jobs.lever.co"
    )


def test_detail_computes_destination_without_adding_it_to_list_items() -> None:
    opportunity = models.Opportunity(
        slug="destination-test",
        title="Research Intern",
        category="internship",
        company=models.Company(slug="semianalysis", name="SemiAnalysis", domain="semianalysis.com"),
        apply_url="https://himalayas.app/companies/semianalysis/jobs/research-intern",
        deadline_confidence="unknown",
        is_hidden=False,
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    detail = OpportunityDetail.from_model(opportunity)
    assert detail.destination.model_dump() == {
        "kind": "job_board",
        "host": "himalayas.app",
        "label": "Himalayas",
    }
    assert "destination" not in OpportunityListItem.from_model(opportunity).model_dump()


@pytest.mark.parametrize(
    "domain,label",
    [
        ("unstop.com", "Unstop"),
        ("devpost.com", "Devpost"),
        ("devfolio.co", "Devfolio"),
        ("hackerearth.com", "HackerEarth"),
    ],
)
def test_event_platform_has_priority_over_company_match(domain: str, label: str) -> None:
    assert classify_destination(f"https://{domain}/event", domain) == ApplyDestination(
        "event_platform", domain, label
    )
