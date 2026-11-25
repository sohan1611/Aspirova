"""TRUST-01 source-shape regression, ownership boundaries and malicious inputs."""

import pytest

from core.destination_facts import (
    DESTINATION_FACTS_VERSION,
    ats_board,
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
        (
            "workday",
            "hp|wd5|externalcareersite",
            "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/1",
        ),
        (
            "workday",
            "baird|wd1|careers",
            "https://wd1.myworkdaysite.com/recruiting/baird/Careers/job/1",
        ),
        (
            "workday",
            "hp|wd5|externalcareersite",
            "https://wd5.myworkdaysite.com/en-US/recruiting/hp/ExternalCareerSite/job/1",
        ),
        (
            "workday",
            "hp|wd5|externalcareersite",
            "https://hp.wd5.myworkdayjobs.com/zh-Hans/ExternalCareerSite/job/1",
        ),
        ("recruitee", "sendcloud", "https://sendcloud.recruitee.com/o/intern"),
        ("recruitee", "SendCloud", "https://sendcloud.recruitee.com/o/intern"),
        ("personio", "acme", "https://acme.jobs.personio.de/job/1"),
        ("personio", "Acme", "https://acme.jobs.personio.com/job/1"),
        ("bamboohr", "Acme", "https://acme.bamboohr.com/careers/1"),
        ("bamboohr", "acme", "https://acme.bamboohr.com/jobs/view.php?id=1"),
        ("greenhouse", "acme", "https://job-boards.eu.greenhouse.io/acme/jobs/1"),
        ("lever", "acme", "https://jobs.lever.co/acme/1"),
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
        "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/1",
        "https://wd5.myworkdaysite.com/recruiting/hp/ExternalCareerSite/job/1",
    ],
)
@pytest.mark.parametrize(
    "board",
    ["other|wd5|externalcareersite", "hp|wd1|externalcareersite", "hp|wd5|othersite", "hp", None],
)
def test_workday_requires_matching_tenant_cluster_and_site(url, board):
    facts = classify_destination_facts(url, ats_type="workday", ats_board_id=board)
    assert facts["type"] == "employer_ats" and not facts["employer_verified"]


@pytest.mark.parametrize(
    "url",
    [
        "https://wd1.myworkdaysite.com/recruiting/baird",
        "https://wd1.myworkdaysite.com/other/baird/careers/job/1",
        "https://evil.wd1.myworkdaysite.com/recruiting/baird/careers/job/1",
        "https://wd1.myworkdaysite.com.evil.com/recruiting/baird/careers/job/1",
        "https://sendcloud.recruitee.com.evil.com/o/intern",
        "https://acme.jobs.personio.com.evil.com/job/1",
        "https://acme.bamboohr.com.evil.com/careers/1",
    ],
)
def test_unrecognized_or_spoofed_board_forms_do_not_verify(url):
    assert ats_board(url) is None


@pytest.mark.parametrize(
    "url,kind,board",
    [
        (
            "https://hp.wd5.myworkdayjobs.com/ExternalCareerSite/job/1",
            "workday",
            "hp|wd5|externalcareersite",
        ),
        ("https://sendcloud.recruitee.com/o/intern", "recruitee", "sendcloud"),
    ],
)
def test_exact_employer_binding_survives_bare_bot_blocks(url, kind, board):
    observation = {
        "url_key": url_key(url),
        "status": "unknown",
        "http_status": 403,
        "warnings": ["blocked_403"],
    }
    facts = classify_destination_facts(
        url, ats_type=kind, ats_board_id=board, observation=observation
    )
    assert facts["employer_verified"] and facts["status"] == "unknown"
    assert not classify_destination_facts(
        url, ats_type=kind, ats_board_id="other", observation=observation
    )["employer_verified"]


@pytest.mark.parametrize(
    "path",
    [
        "/competitions/event-1",
        "/hackathons/event-1",
        "/quiz/event-1",
        "/quizzes/event-1",
        "/",
        "/competitions/jobs-challenge",
    ],
)
def test_unstop_events_are_hosted_on_a_competition_platform(path):
    facts = classify_destination_facts("https://unstop.com" + path, "unstop.com", source="unstop")
    assert facts["type"] == "competition_platform" and facts["platform"] == "Unstop"
    assert not facts["employer_verified"] and not facts["aggregator_warning"]


@pytest.mark.parametrize("path", ["/jobs/role-1", "/internships/role-1", "/jobs", "/internships/"])
def test_unstop_jobs_remain_aggregator_listings(path):
    facts = classify_destination_facts("https://unstop.com" + path, source="unstop")
    assert facts["type"] == "aggregator" and facts["aggregator_warning"]
    assert not facts["employer_verified"]


@pytest.mark.parametrize(
    "host",
    ["arbeitnow.com", "arbeitnow.nl", "www.arbeitnow.de", "jobs.arbeitnow.co.uk", "arbeitnow.jobs"],
)
def test_arbeitnow_country_and_other_tlds_are_aggregators(host):
    facts = classify_destination_facts("https://" + host + "/view/1")
    assert facts["type"] == "aggregator" and facts["via"] == "Arbeitnow"
    assert facts["aggregator_warning"] and not facts["employer_verified"]


@pytest.mark.parametrize(
    "host",
    ["arbeitnow.github.io", "arbeitnow.com.evil.com", "notarbeitnow.nl", "arbeitnow.invalid"],
)
def test_arbeitnow_tenant_and_suffix_spoofs_remain_unknown(host):
    assert classify_destination_facts("https://" + host)["type"] == "unknown"


@pytest.mark.parametrize(
    "host",
    [
        "alpha.devfolio.co",
        "beta.devfolio.co",
        "gamma.devfolio.co",
        "delta.devfolio.co",
        "epsilon.devfolio.co",
        "zeta.devfolio.co",
        "www.hackerearth.com",
        "challenges.hackerearth.com",
        "hackerearth.com",
    ],
)
def test_platform_as_company_never_proves_organiser_origin(host):
    facts = classify_destination_facts("https://" + host + "/hackathon", company_domain=host)
    assert facts["type"] == "competition_platform" and not facts["employer_verified"]


def test_v1_facts_are_recomputed_once_by_the_existing_backfill():
    url = "https://wd1.myworkdaysite.com/recruiting/baird/careers/job/1"
    previous = refresh_destination_facts(url, None, computed_at="old")
    previous["v"] = 1
    assert needs_backfill(previous, url)
    refreshed = refresh_destination_facts(url, previous, computed_at="new")
    assert refreshed["v"] == DESTINATION_FACTS_VERSION == 2
    assert not needs_backfill(refreshed, url)


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
    assert not needs_backfill(result, url)
    assert not needs_backfill({"v": DESTINATION_FACTS_VERSION + 1}, url)


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
    for row, code, status in [
        (sampled[0], 404, "gone"),
        (sampled[1], 401, "sign_in_required"),
        (sampled[2], 403, "unknown"),
    ]:
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
    output = capsys.readouterr().out
    assert "https" not in output and "http403_total=1 http403_correct=1" in output


def test_sampler_keeps_rare_http_boundary_cases():
    rows = [
        {"id": i, "source": f"source{i % 20}", "url": f"https://company{i}.com"} for i in range(500)
    ]
    rows[-1]["observation"] = {"http_status": 404, "status": "gone"}
    rows[-2]["observation"] = {"http_status": 403, "status": "unknown", "warnings": ["blocked_403"]}
    sample = stratify(rows, 100)
    assert {498, 499}.issubset({row["id"] for row in sample})
    assert len(sample) == 100 and len({row["source"] for row in sample}) == 20
