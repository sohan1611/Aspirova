"""Discovery and verification seams; no real network or database."""

from dataclasses import replace

import httpx
import pytest

from core.models import Company
from scripts import discover_boards as discovery
from scripts import seed_boards_batch as seed
from tests.test_seed_boards_batch import FakeSession


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://boards.greenhouse.io/Acme/jobs/123?gh_src=x", ("greenhouse", "Acme")),
        ("https://job-boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
        ("https://boards.eu.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
        ("https://job-boards.eu.greenhouse.io/acme/jobs/123", ("greenhouse", "acme")),
        ("https://boards.greenhouse.io/embed/job_app?token=123&for=Acme", ("greenhouse", "Acme")),
        ("https://jobs.lever.co/acme/123?lever-source=GitHub", ("lever", "acme")),
        ("https://jobs.ashbyhq.com/acme/123/application", ("ashby", "acme")),
        ("https://apply.workable.com/acme/j/123/", ("workable", "acme")),
        ("https://jobs.smartrecruiters.com/Acme/123", ("smartrecruiters", "Acme")),
        ("https://acme.recruitee.com/o/engineering-intern", ("recruitee", "acme")),
        (
            "https://acme.wd5.myworkdayjobs.com/AcmeCareers/job/India/Intern_R123",
            ("workday", "acme|wd5|AcmeCareers"),
        ),
        (
            "https://ACME.wd108.myworkdayjobs.com/en-US/Acme_Careers/job/India/Intern_R123?source=list",
            ("workday", "acme|wd108|Acme_Careers"),
        ),
        (
            "https://acme.wd1.myworkdayjobs.com/fr-FR/Careers?source=github",
            ("workday", "acme|wd1|Careers"),
        ),
        ("https://jobs.lever.co.evil.example/acme/123", None),
        ("https://acme.wd5.myworkdayjobs.com/", None),
        ("https://acme.wd5.myworkdayjobs.com/en-US/", None),
        ("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs", None),
        ("https://boards.greenhouse.io/embed/job_app?token=123", None),
        ("https://example.org/careers", None),
        ("https://one.two.recruitee.com/o/job", None),
        ("https://jobs.lever.co/acme%2Fother/123", None),
    ],
)
def test_url_to_token(url, expected):
    assert discovery.extract_board(url) == expected


def _candidate(name="Acme", token="acme", ats_type="lever", domain=None):
    return seed.BoardCandidate(name, ats_type, token, domain)


def _ok(candidate, count=12):
    return seed.Verification(candidate, True, "ok", count)


def test_known_boards_are_excluded_case_insensitively_and_urls_count_once():
    known = Company(slug="known", name="Known", ats_type="LEVER", ats_board_id="AcMe")
    records = [
        {"company_name": "Acme", "url": "https://jobs.lever.co/acme/123", "active": True},
        {
            "company_name": "Other",
            "url": "https://jobs.ashbyhq.com/other/1?utm_source=one",
            "active": True,
        },
        {
            "company_name": "Other",
            "url": "https://jobs.ashbyhq.com/other/1?source=two",
            "active": True,
        },
        {"company_name": "Other", "url": "https://jobs.ashbyhq.com/other/2", "active": True},
        {"company_name": "Inactive", "url": "https://jobs.lever.co/inactive/1", "active": False},
    ]
    boards = discovery.discover_candidates(records, [known])
    assert len(boards) == 1
    assert boards[0].candidate.board_token == "other"
    assert boards[0].student_listings == 2


def test_max_new_ranks_by_student_count_and_rejects_size_over_cap():
    small = _candidate("Small", "small")
    large = _candidate("Large", "large")
    medium = _candidate("Medium", "medium")
    low = _candidate("Low", "low")
    calls = []

    def verifier(candidate):
        calls.append(candidate)
        return _ok(candidate, 601 if candidate == large else 600)

    boards = [
        discovery.DiscoveredBoard(small, 2),
        discovery.DiscoveredBoard(large, 9),
        discovery.DiscoveredBoard(low, 1),
        discovery.DiscoveredBoard(medium, 5),
    ]
    plan = discovery.plan_discovery(boards, max_new=2, verifier=verifier)
    assert calls == [large, medium, small]
    assert plan.selected == [medium, small]
    assert plan.rows[0][1] == "too_large"
    assert discovery.plan_discovery(boards, max_new=0, verifier=verifier).selected == []


def test_dry_run_writes_nothing_and_apply_attaches_to_existing():
    candidate = _candidate("Existing", "existing-board", domain="existing.example")
    existing = Company(
        slug="existing-from-aggregator",
        name="Existing",
        name_normalized="existing",
        domain="existing.example",
        ats_type=None,
        ats_board_id=None,
    )
    session = FakeSession([existing])
    plan = discovery.plan_discovery([discovery.DiscoveredBoard(candidate, 3)], verifier=_ok)
    summary = discovery.apply_plan(session, plan)
    assert summary.would_attach == [candidate]
    assert session.added == [] and session.commits == 0
    assert existing.ats_type is None and existing.ats_board_id is None
    applied = discovery.apply_plan(session, plan, apply=True)
    assert applied.attached == [candidate]
    assert session.added == [] and session.commits == 1


def test_workday_slug_is_url_safe_and_rerun_is_idempotent():
    candidate = _candidate("Workday Co", "acme|wd5|Careers", "workday")
    session = FakeSession()
    plan = discovery.plan_discovery([discovery.DiscoveredBoard(candidate, 1)], verifier=_ok)
    assert discovery.apply_plan(session, plan, apply=True).inserted == [candidate]
    assert session.added[0].slug == "acme-wd5-careers"
    assert session.added[0].ats_board_id == "acme|wd5|Careers"
    assert discovery.apply_plan(session, plan, apply=True).unchanged == [candidate]


def test_verifier_uses_bogus_control_live_total_and_honors_accepted(monkeypatch):
    candidate = _candidate()
    calls = []

    def probe(value, *, timeout):
        calls.append(value)
        return ("valid", 601) if value == candidate else ("invalid", None)

    monkeypatch.setattr(seed, "_inventory_probe", probe)
    verification = discovery.verify_discovered(candidate)
    assert calls[-1] == candidate and calls[0].board_token.startswith("aspirova-invalid-")
    assert verification.reason == "too_large" and verification.listings_count == 601
    assert verification.accepted is False and verification.health == "ok"
    session = FakeSession()
    summary = seed.run_batch(
        session, [candidate], apply=True, verifier=lambda _candidate: verification, verify_workers=1
    )
    assert summary.rejected == [verification]
    assert session.added == [] and session.commits == 0


@pytest.mark.parametrize("status", ["valid", "failed"])
def test_bogus_control_must_fail_conclusively(monkeypatch, status):
    candidate = _candidate()
    monkeypatch.setattr(
        seed,
        "_inventory_probe",
        lambda *args, **kwargs: (status, 20 if status == "valid" else None),
    )
    result = discovery.verify_discovered(candidate)
    assert not result.accepted
    assert result.reason == f"bogus_control_{status}"


def test_workday_verifier_uses_one_probe_and_ignores_full_board_cap(monkeypatch):
    candidate = _candidate("Workday Co", "acme|wd5|Careers", "workday")
    tokens = []

    def probe(value, *, timeout):
        tokens.append(value.board_token)
        return "valid", 2887

    monkeypatch.setattr(seed, "_inventory_probe", probe)
    result = discovery.verify_discovered(candidate)
    assert result.accepted and result.listings_count == 2887
    assert tokens == [candidate.board_token]
    plan = discovery.plan_discovery(
        [discovery.DiscoveredBoard(candidate, 4)], verifier=lambda _candidate: result
    )
    assert plan.selected == [candidate]
    assert plan.rows[0][1] == "verified"


def test_workday_zero_intern_hits_are_rejected(monkeypatch):
    monkeypatch.setattr(seed, "_inventory_probe", lambda *args, **kwargs: ("valid", 0))
    candidate = _candidate("Workday Co", "acme|wd5|Careers", "workday")
    result = discovery.verify_discovered(candidate)
    assert not result.accepted and result.reason == "no_intern_results"


def test_rejected_candidates_stop_at_max_verify():
    boards = [
        discovery.DiscoveredBoard(_candidate(f"Company {index}", f"board-{index}"), 200 - index)
        for index in range(160)
    ]
    calls = []

    def reject(candidate):
        calls.append(candidate)
        return seed.Verification(candidate, False, "degraded", None, "fixture rejection")

    plan = discovery.plan_discovery(boards, verifier=reject)
    assert len(calls) == 150 and len(plan.rows) == 150 and not plan.selected
    calls.clear()
    plan = discovery.plan_discovery(boards, verifier=reject, max_verify=3)
    assert len(calls) == 3 and len(plan.rows) == 3
    assert discovery.plan_discovery(boards, verifier=reject, max_verify=0).rows == []


def test_workday_inventory_probe_posts_only_intern_search(monkeypatch):
    import json
    from pathlib import Path
    from crawlers import workday

    captured = json.loads(
        (Path(__file__).parent / "fixtures" / "workday_search_sample.json").read_text(
            encoding="utf-8-sig"
        )
    )
    requests = []
    real_client = httpx.Client

    def respond(request):
        requests.append(request)
        assert request.method == "POST"
        assert json.loads(request.content)["searchText"] == "intern"
        return httpx.Response(200, json=captured | {"total": 2887})

    monkeypatch.setattr(workday, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        seed.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    candidate = _candidate("Workday Co", "acme|wd5|Careers", "workday")
    result = discovery.verify_discovered(candidate)
    assert result.accepted and result.listings_count == 2887
    assert len(requests) == 1


def test_smartrecruiters_probe_counts_declared_total_without_detail_fetch(monkeypatch):
    requests = []
    real_client = httpx.Client

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"content": [{"id": "one"}], "totalFound": 900})

    monkeypatch.setattr(
        seed.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(seed, "sleep", lambda _delay: None)
    assert seed._inventory_probe(_candidate(ats_type="smartrecruiters"), timeout=5) == (
        "valid",
        900,
    )
    assert len(requests) == 1 and requests[0].url.params["limit"] == "1"


def test_no_slug_collision_or_overwrite_for_different_boards():
    first = _candidate("First Co", "shared-token", "lever")
    second = replace(first, company_name="Second Co", ats_type="ashby")
    session = FakeSession()
    summary = seed.run_batch(session, [first, second], apply=True, verifier=_ok, verify_workers=1)
    assert summary.inserted == [first]
    assert len(summary.conflicts) == 1
    assert len(session.added) == 1
