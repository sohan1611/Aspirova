"""Workday positive-list coverage, block skips and defensible reopens."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from core import models
from core.freshness import last_verified
from pipeline import liveness
from pipeline.ingest import _listing_meta
from scripts import liveness_reopens


@pytest.fixture
def session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection) as session:
            yield session
        transaction.rollback()


def listing(source, url, now, *, age=9, closed=False):
    return models.Opportunity(
        slug=uuid4().hex,
        title="Software Engineer Intern",
        category="job",
        primary_source=source,
        status="active",
        apply_url=url,
        first_seen_at=now - timedelta(days=100),
        last_seen_at=now - timedelta(days=age),
        closed_at=now - timedelta(days=1) if closed else None,
        meta={"closed_reason": "rolling_window_ttl"} if closed else {},
    )


def mock_http(monkeypatch, respond):
    client = httpx.Client
    inspect = liveness.inspect_destination
    monkeypatch.setattr(
        liveness, "inspect_destination", lambda *a, **k: inspect(*a, resolve=lambda *_: True, **k)
    )
    monkeypatch.setattr(liveness, "public_dns", lambda *_: True)
    monkeypatch.setattr(liveness, "sleep", lambda _: None)
    monkeypatch.setattr(
        liveness.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(respond), **kw)
    )


def test_cxs_list_verifies_exact_paths_and_never_closes_unlisted_rows(session, monkeypatch):
    now = datetime.now(timezone.utc)
    base = "https://board.wd5.myworkdayjobs.com/en-US"
    rows = [
        listing("workday", f"{base}/Careers/job/{name}", now)
        for name in ("first_R1", "second_R2", "absent_R3")
    ] + [listing("workday", f"{base}/OtherSite/job/{name}", now) for name in ("first_R1", "R4")]
    session.add_all(rows)
    session.flush()
    original_facts = [row.destination_facts for row in rows]
    calls = []

    def respond(request):
        query = json.loads(request.content)
        offset = query["offset"]
        assert request.method == "POST" and query["limit"] == 20
        assert query["searchText"] == "intern"
        calls.append((request.url.path, offset))
        if "/OtherSite/" in request.url.path:
            return httpx.Response(404)

        def posting(path):
            return {"externalPath": f"/job/{path}", "title": "Software Engineer Intern"}

        if offset == 0:
            jobs = [posting("first_R1"), posting("wrong-identity_R3")]
            jobs += [posting(f"irrelevant_{i}") for i in range(18)]
            return httpx.Response(200, json={"total": 22, "jobPostings": jobs})
        return httpx.Response(200, json={"total": 0, "jobPostings": [posting("second_R2")]})

    mock_http(monkeypatch, respond)
    result = liveness.check_listing_liveness(
        session, apply=True, freshness_mode=True, now=now, commit_each_batch=False
    )
    session.expire_all()
    assert sorted(calls) == [
        ("/wday/cxs/board/Careers/jobs", 0),
        ("/wday/cxs/board/Careers/jobs", 20),
        ("/wday/cxs/board/OtherSite/jobs", 0),
    ]
    assert (result.scanned, result.alive, result.closed, result.reopened, result.skipped) == (
        2,
        2,
        0,
        0,
        3,
    )
    assert result.workday_list == {"requests": 3, "pages": 2, "verified": 2, "404": 1}
    for row in rows[:2]:
        assert last_verified(row) >= now
        assert row.destination_facts["observation"]["evidence"] == "workday_cxs_list"
    for row, initial in zip(rows[2:], original_facts[2:]):
        assert last_verified(row) == row.last_seen_at
        assert row.destination_facts == initial and row.meta == {} and row.closed_at is None


def test_403_burst_skips_remaining_host_and_far_from_stale_rows(session, monkeypatch):
    now = datetime.now(timezone.utc)
    blocked = [
        listing(
            "himalayas",
            f"https://{'www.' if i % 2 else ''}himalayas.app/jobs/{i}",
            now,
            age=70,
        )
        for i in range(6)
    ]
    far = listing("himalayas", "https://himalayas.app/jobs/far", now, age=10)
    other = listing("jobicy", "https://jobicy.com/jobs/other", now, age=40)
    session.add_all([*blocked, far, other])
    session.flush()
    requests = []

    def respond(request):
        requests.append(request.url.path)
        assert request.url.path != "/jobs/far"
        return httpx.Response(200 if request.url.host == "jobicy.com" else 403)

    mock_http(monkeypatch, respond)
    result = liveness.check_listing_liveness(
        session, apply=True, freshness_mode=True, concurrency=1, now=now, commit_each_batch=False
    )
    assert len(requests) == 4 and "/jobs/other" in requests
    counts = result.by_source["himalayas"]
    assert (counts.inconclusive, counts.closed, counts.skipped) == (3, 0, 3)
    assert counts.reasons == {"403": 3, "skipped_403": 3}
    session.expire_all()
    assert sum("liveness_checked_at" in row.meta for row in blocked) == 3
    assert far.meta == {}
    assert all(row.closed_at is None for row in blocked)


def test_workday_429_escalates_and_403_burst_stops_centre(monkeypatch):
    clock = 0.0
    replies = iter([429, 429, 403, 403, 403])
    seen = []

    def advance(delay):
        nonlocal clock
        clock += delay

    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(next(replies), headers={"Retry-After": "45"})

    monkeypatch.setattr(liveness, "sleep", advance)
    monkeypatch.setattr(liveness, "monotonic", lambda: clock)
    checker = liveness.WorkdayLivenessChecker(deadline=500)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        for index, wait in enumerate((45, 60)):
            response = checker._request(client, "GET", f"https://t{index}.wd5.myworkdayjobs.com/")
            assert response.status_code == 429
            assert checker.cooldown_until["wd5"] == clock + wait
            clock += wait
        for index in range(3):
            response = checker._request(client, "GET", f"https://x{index}.wd5.myworkdayjobs.com/")
            assert response.status_code == 403
        with pytest.raises(liveness.CheckBudgetExceeded):
            checker._request(client, "GET", "https://unused.wd5.myworkdayjobs.com/")
    assert len(seen) == 5 and checker.forbidden.blocked("wd5")
    assert not checker.forbidden.blocked("wd3")


def test_reopens_need_more_than_a_retained_rolling_feed_page(session, monkeypatch):
    now = datetime.now(timezone.utc)
    rows = [
        listing("arbeitnow", "https://www.arbeitnow.ch/jobs/archive", now, age=40, closed=True),
        listing("remoteok", "https://remoteok.com/remote-jobs/old", now, age=40, closed=True),
        listing("jobicy", "https://employer.example.org/jobs/expired", now, age=40, closed=True),
        listing("jobicy", "https://employer.example.org/jobs/current", now, age=40, closed=True),
    ]
    session.add_all(rows)
    session.flush()

    def respond(request):
        html = "<h1>Software Engineer Intern</h1>"
        if request.url.path.endswith("/expired"):
            html += "<p>This job posting is no longer available.</p>"
        return httpx.Response(200, text=html)

    mock_http(monkeypatch, respond)
    result = liveness.check_listing_liveness(
        session, apply=True, freshness_mode=True, concurrency=1, now=now, commit_each_batch=False
    )
    session.expire_all()
    assert result.reopened == 1
    assert [row.closed_at is None for row in rows] == [False, False, False, True]
    assert rows[2].destination_facts["status"] == "unknown"
    counts = liveness_reopens.reopen_counts(session, since=now - timedelta(days=7))
    assert [(row.source, row.liveness) for row in counts if row.liveness] == [("jobicy", 1)]


def test_reopen_cli_runs_read_only(engine, monkeypatch, capsys):
    def counts(connection, *, since):
        assert connection.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
        assert since < datetime.now(timezone.utc)
        return []

    monkeypatch.setattr(liveness_reopens, "make_engine", lambda: engine)
    monkeypatch.setattr(liveness_reopens, "reopen_counts", counts)
    monkeypatch.setattr("sys.argv", ["liveness_reopens", "--days", "3"])
    liveness_reopens.main()
    assert (
        capsys.readouterr().out.strip()
        == "LIVENESS REOPENS total: days=3 liveness=0 unattributed=0"
    )


def test_ingest_preserves_liveness_reopen_evidence():
    key = "liveness_reopened_at"
    row = SimpleNamespace(category="hackathon", meta={key: "source supplied"})
    assert key not in (_listing_meta(row, None) or {})
    assert _listing_meta(row, None, {key: "stored"})[key] == "stored"
