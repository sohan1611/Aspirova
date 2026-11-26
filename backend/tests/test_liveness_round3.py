"""Workday scheduling, positive CXS evidence, and counts-only output."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from threading import Event, Lock
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from core import models
from pipeline import liveness
from scripts import check_listing_liveness as cli


def workday_url(host: str, path: str, cluster: str = "wd5") -> str:
    return f"https://{host}.{cluster}.myworkdayjobs.com/PrivateSite/job/{path}"


def test_ready_tenants_finish_while_a_500_row_tenant_is_blocked():
    candidates = [
        liveness.LivenessCandidate(i, workday_url("large", str(i))) for i in range(500)
    ] + [
        liveness.LivenessCandidate(500 + i, workday_url(host, str(i), cluster))
        for i, (host, cluster) in enumerate((("small", "wd1"), ("medium", "wd3")) * 12)
    ]
    candidates.append(liveness.LivenessCandidate(524, workday_url("same-cluster", "same")))
    first_large_started = Event()
    release_large = Event()
    other_tenants_finished = Event()
    same_cluster_started = Event()
    active_hosts: set[str] = set()
    completed: list[int] = []
    collisions: list[str] = []
    lock = Lock()

    def check(candidate):
        host = liveness._workday_host(candidate.apply_url)
        with lock:
            if host in active_hosts:
                collisions.append(host)
                return "inconclusive", None
            active_hosts.add(host)
        if candidate.id == 0:
            first_large_started.set()
            release_large.wait(5)
        if candidate.id == 524:
            same_cluster_started.set()
        with lock:
            active_hosts.remove(host)
            completed.append(candidate.id)
            if len(completed) == 24 and min(completed) == 500:
                other_tenants_finished.set()
        return "alive", None

    with ThreadPoolExecutor(max_workers=1) as runner:
        scheduled = runner.submit(
            lambda: list(
                liveness._checked_batches(
                    candidates,
                    checker=check,
                    concurrency=3,
                    batch_size=50,
                    deadline=monotonic() + 10,
                    cooldown_until={},
                )
            )
        )
        try:
            assert first_large_started.wait(3)
            assert other_tenants_finished.wait(3)
            assert not same_cluster_started.is_set()
        finally:
            release_large.set()
        batches = scheduled.result(timeout=5)

    assert not collisions
    assert [index for index in completed if index < 500] == list(range(500))
    assert sum(len(batch) for batch in batches) == 525
    assert same_cluster_started.is_set()


def test_soft_budget_finishes_in_flight_work_and_leaves_other_rows_unattempted(monkeypatch):
    clock = 0
    candidates = [liveness.LivenessCandidate(i, f"https://example.org/jobs/{i}") for i in range(4)]

    def check(_candidate):
        nonlocal clock
        clock = 1
        return "alive", None

    monkeypatch.setattr(liveness, "monotonic", lambda: clock)
    batches = list(
        liveness._checked_batches(
            candidates,
            checker=check,
            concurrency=1,
            batch_size=50,
            deadline=1,
            cooldown_until={},
        )
    )
    assert batches == [[(candidates[0], "alive", None)]]


@pytest.fixture
def mock_public_dns(monkeypatch):
    original = liveness.inspect_destination
    monkeypatch.setattr(
        liveness,
        "inspect_destination",
        lambda *args, **kwargs: original(*args, resolve=lambda *_: True, **kwargs),
    )


def test_workday_paces_shared_host_across_sites_and_retries(monkeypatch, mock_public_dns):
    clock = 0.0
    requests = []

    def advance(delay):
        nonlocal clock
        clock += delay

    def respond(_request):
        requests.append(clock)
        if len(requests) == 1:
            return httpx.Response(502, headers={"Retry-After": "2"})
        return httpx.Response(404)

    monkeypatch.setattr(liveness, "sleep", advance)
    checker = liveness.WorkdayLivenessChecker()
    urls = [
        workday_url("paced", "one"),
        workday_url("paced", "two").replace("PrivateSite", "Other"),
    ]
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(lambda url: checker.check(url, client), urls)) == ["closed"] * 2
    delay = liveness.REQUEST_DELAY_SECONDS
    assert requests == [delay, 2 + 2 * delay, 2 + 3 * delay]


@pytest.mark.parametrize(
    "body",
    [
        "<html><h1>Careers</h1></html>",
        "[]",
        '{"error":"unavailable"}',
        '{"jobPostingInfo":{"title":"", "jobDescription":""}}',
        '{"jobPostingInfo":{"title":"Engineer", "jobDescription":[]}}',
    ],
)
def test_workday_requires_posting_detail_on_2xx(body, monkeypatch, mock_public_dns):
    monkeypatch.setattr(liveness, "sleep", lambda _: None)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))
    ) as client:
        observation = liveness.fetch_destination_observation(workday_url("shape", "job"), client)
    assert liveness.observation_liveness(observation) == "inconclusive"
    assert liveness._inconclusive_reason(observation) == "parse_or_shape"


def test_workday_retry_after_past_deadline_preserves_status_and_defers_host(
    monkeypatch, mock_public_dns
):
    def assert_pacing(delay):
        assert delay == liveness.REQUEST_DELAY_SECONDS

    monkeypatch.setattr(liveness, "sleep", assert_pacing)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    checker = liveness.WorkdayLivenessChecker(monotonic() + 10)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        first = checker.observe(workday_url("rate-limited", "one"), client)
        second = checker.observe(workday_url("another-tenant", "two"), client)
    assert len(calls) == 1
    assert liveness._inconclusive_reason(first) == "429"
    assert liveness._inconclusive_reason(second) == "lock_or_budget"


@pytest.mark.parametrize("signal", [429, 503, "timeout"])
def test_shared_cluster_backoff_keeps_other_work_running(signal, monkeypatch, mock_public_dns):
    clock = 0.0
    now = datetime(2026, 11, 26, tzinfo=timezone.utc)
    calls = []
    urls = [
        workday_url("first", "throttle"),
        workday_url("second", "throttle") if signal == "timeout" else workday_url("second", "ok"),
        workday_url("third", "ok"),
        workday_url("different", "ok", "wd12"),
        "https://other-source.example.org/jobs/ok",
    ]
    candidates = [liveness.LivenessCandidate(i, url) for i, url in enumerate(urls)]
    parse_retry_after = liveness.retry_after_seconds
    monkeypatch.setattr(
        liveness,
        "retry_after_seconds",
        lambda response: parse_retry_after(response, now=lambda: now),
    )

    def advance(delay):
        nonlocal clock
        clock += delay

    def respond(request):
        calls.append((request.url.host, clock))
        if request.url.path.endswith("/throttle"):
            if signal == "timeout":
                raise httpx.ReadTimeout("fixture timeout", request=request)
            headers = {
                "Retry-After": (
                    "47"
                    if signal == 429
                    else format_datetime(now + timedelta(seconds=47), usegmt=True)
                )
            }
            return httpx.Response(signal, headers=headers)
        return httpx.Response(
            200, json={"jobPostingInfo": {"title": "Test Engineer", "jobDescription": ""}}
        )

    monkeypatch.setattr(liveness, "monotonic", lambda: clock)
    monkeypatch.setattr(liveness, "sleep", advance)
    checker = liveness.WorkdayLivenessChecker(deadline=120)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:

        def check(candidate):
            observation = liveness.fetch_destination_observation(
                candidate.apply_url, client, workday_checker=checker
            )
            return liveness.observation_liveness(observation), observation

        batches = liveness._checked_batches(
            candidates,
            checker=check,
            concurrency=1,
            batch_size=50,
            deadline=120,
            cooldown_until=checker.cooldown_until,
        )
        outcomes = {
            candidate.id: (status, liveness._inconclusive_reason(observation))
            for batch in batches
            for candidate, status, observation in batch
        }

    before_pause = liveness.WORKDAY_TIMEOUT_BURST if signal == "timeout" else 1
    assert outcomes[0] == ("inconclusive", {429: "429", 503: "5xx", "timeout": "timeout"}[signal])
    if signal == "timeout":
        assert outcomes[1] == ("inconclusive", "timeout")
    else:
        assert outcomes[1][0] == "alive"
    assert all(outcomes[i][0] == "alive" for i in (2, 3, 4))
    assert [host for host, _ in calls[before_pause : before_pause + 2]] == [
        "different.wd12.myworkdayjobs.com",
        "other-source.example.org",
    ]
    last_failure_at = calls[before_pause - 1][1]
    resumed_at = calls[before_pause + 2][1]
    wait = liveness.WORKDAY_BACKOFF_SECONDS if signal == "timeout" else 47
    assert resumed_at == pytest.approx(last_failure_at + wait + liveness.REQUEST_DELAY_SECONDS)
    same_cluster_times = [at for host, at in calls if ".wd5." in host]
    assert all(
        later - earlier >= liveness.REQUEST_DELAY_SECONDS
        for earlier, later in zip(same_cluster_times, same_cluster_times[1:])
    )


@pytest.mark.parametrize("apply", [True, False])
def test_source_totals_and_all_reason_buckets_in_cli(
    engine,
    monkeypatch,
    capsys,
    mock_public_dns,
    apply,
):
    real_client = httpx.Client
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex
    scenarios = {
        "timeout": "workday",
        "403": "workday",
        "429": "workday",
        "503": "workday",
        "401": "workday",
        "shape": "workday",
        "budget": "workday",
        "302": "workday",
        "parked": "workday",
        "404": "workday",
        "410": "amazon",
        "fresh-reopen": "amazon",
        "200": "custom-private-source",
    }

    def respond(request):
        scenario = request.url.path.rsplit("/", 1)[-1]
        if scenario == "timeout":
            raise httpx.ReadTimeout("private-transport-message", request=request)
        if scenario == "budget":
            raise liveness.CheckBudgetExceeded
        if scenario in {"shape", "fresh-reopen"}:
            return httpx.Response(200, text="<h1>Senior Engineer</h1>")
        if scenario == "parked":
            return httpx.Response(200, text="This domain is for sale")
        return httpx.Response(int(scenario), headers={"Retry-After": "0"})

    monkeypatch.setattr(
        liveness.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(liveness, "sleep", lambda _: None)
    monkeypatch.setattr(cli, "make_engine", lambda: engine)
    notified = []
    monkeypatch.setattr(cli, "notify_changed", notified.append)
    monkeypatch.setattr("sys.argv", ["check_listing_liveness", "--apply" if apply else "--dry-run"])

    with Session(engine) as setup:
        rows = [
            models.Opportunity(
                slug=f"private-{suffix}-{scenario}",
                title="Senior Engineer",
                category="job",
                status="active",
                apply_url=(
                    workday_url("private-tenant", scenario, f"wd{index}")
                    if source == "workday"
                    else f"https://private-host.example.org/jobs/{scenario}"
                ),
                primary_source=source,
                first_seen_at=now - timedelta(days=50),
                last_seen_at=(
                    now + timedelta(days=1) if scenario == "410" else now - timedelta(days=9)
                ),
                closed_at=now - timedelta(days=2) if scenario == "fresh-reopen" else None,
                meta={"closed_reason": "rolling_window_ttl"} if scenario == "fresh-reopen" else {},
            )
            for index, (scenario, source) in enumerate(scenarios.items(), start=1)
        ]
        setup.add_all(rows)
        setup.flush()
        candidates = [
            liveness.LivenessCandidate(
                row.id, row.apply_url, title=row.title, source=row.primary_source
            )
            for row in rows
        ]
        monkeypatch.setattr(liveness, "_select_freshness_candidates", lambda *a, **k: candidates)
        # Bind the CLI to the fixture transaction so it can see the uncommitted rows.
        connection = setup.connection()
        monkeypatch.setattr(cli, "Session", lambda _: Session(connection))
        before = [(row.meta, row.destination_facts, row.closed_at) for row in rows]
        cli.main()
        lines = capsys.readouterr().out.splitlines()
        if not apply:
            setup.expire_all()
            assert [(row.meta, row.destination_facts, row.closed_at) for row in rows] == before
            assert not notified

    assert lines[:7] == [
        f"mode: {'apply' if apply else 'dry-run'}",
        "listings scanned: 13",
        f"listings closed: {1 if apply else 2}",
        "listings alive: 2",
        f"listings reopened: {int(apply)}",
        "listings inconclusive: 9",
        "time budget exhausted: no",
    ]
    assert (
        f"LIVENESS SOURCE amazon: scanned=2 alive=1 closed={int(not apply)} "
        f"reopened={int(apply)} inconclusive=0"
    ) in lines
    assert "LIVENESS SOURCE workday: scanned=10 alive=0 closed=1 reopened=0 inconclusive=9" in lines
    assert "LIVENESS SOURCE other: scanned=1 alive=1 closed=0 reopened=0 inconclusive=0" in lines
    assert (
        "LIVENESS INCONCLUSIVE workday: timeout=1 403=1 429=1 5xx=1 other_4xx=1 "
        "parse_or_shape=1 redirect=1 lock_or_budget=1 other=1"
    ) in lines
    assert "private" not in "\n".join(lines)
