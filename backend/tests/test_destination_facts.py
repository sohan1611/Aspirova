"""TRUST-01 source-shape regression, ownership boundaries and malicious inputs."""

import pytest

from core.destination_facts import (
    classify_destination_facts,
    public_host,
    refresh_destination_facts,
    registrable_domain,
    url_key,
)
from scripts.backfill_destination_facts import needs_backfill
from scripts.destination_eval import score, stratify


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    yield


@pytest.mark.parametrize(
    "source,url,kind,domain",
    [
        (
            "greenhouse",
            "https://job-boards.greenhouse.io/acme/jobs/1",
            "employer_ats",
            "greenhouse.io",
        ),
        ("lever", "https://jobs.lever.co/acme/1", "employer_ats", "lever.co"),
        ("ashby", "https://jobs.ashbyhq.com/acme/1/application", "employer_ats", "ashbyhq.com"),
        (
            "workday",
            "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/India/1",
            "employer_ats",
            "myworkdayjobs.com",
        ),
        (
            "smartrecruiters",
            "https://jobs.smartrecruiters.com/acme/1",
            "employer_ats",
            "smartrecruiters.com",
        ),
        ("workable", "https://apply.workable.com/acme/j/1", "employer_ats", "workable.com"),
        ("recruitee", "https://acme.recruitee.com/o/intern", "employer_ats", "recruitee.com"),
        ("keka", "https://acme.keka.com/careers/jobdetails/1", "employer_ats", "keka.com"),
        ("amazon", "https://www.amazon.jobs/en/jobs/1", "employer_site", "amazon.jobs"),
        ("arbeitnow", "https://www.arbeitnow.com/view/1", "aggregator", "arbeitnow.com"),
        (
            "himalayas",
            "https://himalayas.app/companies/acme/jobs/intern",
            "aggregator",
            "himalayas.app",
        ),
        ("jobicy", "https://jobicy.com/jobs/1-intern", "aggregator", "jobicy.com"),
        ("remoteok", "https://remoteok.com/remote-jobs/1", "aggregator", "remoteok.com"),
        ("remotive", "https://remotive.com/remote-jobs/1", "aggregator", "remotive.com"),
        ("unstop", "https://unstop.com/internships/intern-1", "aggregator", "unstop.com"),
        ("devpost", "https://acme.devpost.com/", "competition_platform", "devpost.com"),
        ("devfolio", "https://acme.devfolio.co/", "competition_platform", "devfolio.co"),
        (
            "hackerearth",
            "https://www.hackerearth.com/challenges/hackathon/1/",
            "competition_platform",
            "hackerearth.com",
        ),
        ("github_lists", "https://careers.acme.com/jobs/1", "unknown", "acme.com"),
        (
            "github_lists",
            "https://github.com/SimplifyJobs/Summer2027-Internships",
            "aggregator",
            "github.com",
        ),
        ("isro", "https://www.isro.gov.in/notice.pdf", "government", "isro.gov.in"),
        ("drdo", "https://drdo.gov.in/drdo/careers", "government", "drdo.gov.in"),
        (
            "meity_careers",
            "https://www.meity.gov.in/static/uploads/notice.pdf",
            "government",
            "meity.gov.in",
        ),
        ("nec_internships", "https://necouncil.gov.in/notice", "government", "necouncil.gov.in"),
        ("nic_dii", "https://dii.nic.in/schedule", "government", "dii.nic.in"),
        ("calendar", "https://www.iitm.ac.in/admissions", "academic", "iitm.ac.in"),
        ("calendar", "https://university.edu/programme", "academic", "university.edu"),
        ("discovery", "https://example.co.uk/careers", "unknown", "example.co.uk"),
    ],
)
def test_every_source_shape(source, url, kind, domain):
    facts = classify_destination_facts(url, source=source)
    assert facts["valid"] and facts["type"] == kind and facts["domain"] == domain
    assert not facts["employer_verified"]
    assert facts["aggregator_warning"] == (
        source
        in {"arbeitnow", "himalayas", "jobicy", "remoteok", "remotive", "unstop", "github_lists"}
    )


@pytest.mark.parametrize(
    "kind,board,url",
    [
        ("greenhouse", "acme", "https://boards.eu.greenhouse.io/acme/jobs/1"),
        ("greenhouse", "acme", "https://boards.greenhouse.io/embed/job_app?for=acme&token=1"),
        ("lever", "acme", "https://jobs.eu.lever.co/acme/1"),
        ("ashby", "acme", "https://jobs.ashbyhq.com/acme/1"),
        ("smartrecruiters", "Acme", "https://jobs.smartrecruiters.com/Acme/1"),
        ("workable", "acme", "https://apply.workable.com/acme/j/1"),
        ("recruitee", "acme", "https://acme.recruitee.com/o/1"),
        ("keka", "acme", "https://acme.keka.com/careers/jobdetails/1"),
        ("workday", "acme|wd5|Careers", "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/1"),
    ],
)
def test_exact_company_board_evidence(kind, board, url):
    assert classify_destination_facts(url, ats_type=kind, ats_board_id=board)["employer_verified"]
    assert not classify_destination_facts(url, ats_type=kind, ats_board_id=board + "x")[
        "employer_verified"
    ]
    assert not classify_destination_facts(url, ats_type="other", ats_board_id=board)[
        "employer_verified"
    ]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/plain,a",
        "mailto:apply@example.com",
        "ftp://example.com",
        "https://user:pass@example.com",
        "https://@example.com",
        "https://localhost/job",
        "https://foo.localhost/",
        "http://127.0.0.1",
        "http://127.1",
        "http://2130706433",
        "http://0x7f000001",
        "http://0177.0.0.1",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254",
        "http://100.64.0.1",
        "http://[::1]",
        "http://[fe80::1]",
        "http://[::ffff:127.0.0.1]",
        "http://224.0.0.1",
        "http://[ff02::1]",
        "https://example.com:bad",
        "https://example.com:65536",
        "https://example.com:0",
        "https://bad_host.com",
        "https://-bad.com",
        "https://example..com",
        "https://xn--.com",
        "https://foo%2ecom",
        "https://bad host.com",
        "https://example.com\\@evil.com",
        "https://example.com/\npath",
        "//example.com/path",
        "https://[broken",
        "",
    ],
)
def test_unsafe_or_malformed(url):
    facts = classify_destination_facts(url)
    assert not facts["valid"] and facts["host"] is None and not facts["employer_verified"]


def test_idn_tracking_and_suffix_boundaries():
    a = classify_destination_facts("https://careers.bücher.de/jobs/1?utm_source=x&token=private")
    b = classify_destination_facts("https://careers.xn--bcher-kva.de/jobs/1")
    assert a["domain"] == b["domain"] == "xn--bcher-kva.de"
    assert "private" not in str(a)
    assert registrable_domain("one.github.io") != registrable_domain("two.github.io")
    assert registrable_domain("careers.example.co.uk") == "example.co.uk"
    assert registrable_domain("co.uk") is None
    assert public_host("https://8.8.8.8/") == "8.8.8.8"
    assert classify_destination_facts("mailto:apply@example.com", email_apply=True)["valid"]


def test_ownership_never_guessed_and_reposter_remains_disclosed():
    assert classify_destination_facts("https://careers.acme.com/jobs", "acme.com")[
        "employer_verified"
    ]
    for url, company in [
        ("https://acme.com.evil.com", "acme.com"),
        ("https://notacme.com", "acme.com"),
        ("https://any.co.uk", "co.uk"),
        ("https://acme.github.io", "github.io"),
        ("https://himalayas.app", "himalayas.app"),
        ("https://jobs.lever.co/evil/1", "lever.co"),
    ]:
        assert not classify_destination_facts(url, company)["employer_verified"]
    facts = classify_destination_facts(
        "https://careers.acme.com", "acme.com", source="github_lists"
    )
    assert facts["employer_verified"] and facts["aggregator_warning"]


def test_observation_invalidated_after_link_change_and_computation_is_stable():
    url = "https://careers.acme.com/job/1"
    observation = {
        "url_key": url_key(url),
        "status": "sign_in_required",
        "warnings": [],
        "checked_at": "2026-11-24T00:00:00+00:00",
    }
    previous = {"observation": observation}
    result = refresh_destination_facts(url, previous, computed_at="2026-11-25T00:00:00+00:00")
    assert result["status"] == "sign_in_required"
    assert result["checked_at"] == observation["checked_at"]
    assert refresh_destination_facts(url, result, computed_at="later") is result
    changed = refresh_destination_facts(url + "2", result, computed_at="later")
    assert changed["status"] == "unchecked" and changed["checked_at"] is None
    assert changed["computed_at"] == "later"
    assert needs_backfill(None, url) and needs_backfill({}, url)
    assert not needs_backfill(result, url) and not needs_backfill({"v": 2}, url)


def test_company_evidence_and_source_changes_are_detected_without_a_url_change():
    url = "https://jobs.lever.co/acme/1"
    context = dict(source="lever", company_id=1, ats_type="lever", ats_board_id="acme")
    facts = refresh_destination_facts(url, None, computed_at="first", **context)
    assert not needs_backfill(facts, url, **context)
    assert needs_backfill(facts, url, **{**context, "ats_board_id": "other"})
    assert needs_backfill(facts, url, **{**context, "company_id": 2})
    assert needs_backfill(facts, url, **{**context, "source": "github_lists"})


def test_stratified_hundred_and_counts_only_eval(capsys):
    rows = [
        {"id": i, "source": f"source{i % 20}", "url": f"https://careers.company{i}.com"}
        for i in range(120)
    ]
    sampled = stratify(rows, 100)
    assert len(sampled) == 100 and len({r["source"] for r in sampled[:20]}) == 20
    for row, code, status in [(sampled[0], 404, "gone"), (sampled[1], 403, "sign_in_required")]:
        row["observation"] = {
            "url_key": url_key(row["url"]),
            "http_status": code,
            "status": status,
            "warnings": [],
        }
    labels = [
        {
            "id": row["id"],
            "type": "unknown",
            "domain": registrable_domain(public_host(row["url"])),
            "status": (row.get("observation") or {}).get("status", "unchecked"),
            "employer_verified": False,
            "valid": True,
        }
        for row in sampled
    ]
    _, passed = score(sampled, labels)
    assert passed
    labels[0]["type"] = "aggregator"
    _, passed = score(sampled, labels)
    assert not passed
    assert "https" not in capsys.readouterr().out


def test_sampler_keeps_rare_http_boundary_cases():
    rows = [
        {"id": i, "source": f"source{i % 20}", "url": f"https://company{i}.com"} for i in range(500)
    ]
    rows[-1]["observation"] = {"http_status": 404, "status": "gone"}
    rows[-2]["observation"] = {"http_status": 403, "status": "sign_in_required"}
    sample = stratify(rows, 100)
    assert {498, 499}.issubset({row["id"] for row in sample})
    assert len(sample) == 100 and len({row["source"] for row in sample}) == 20
