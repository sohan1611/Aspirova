"""ATS board evidence from HTTP fixtures only; no live requests."""

from types import SimpleNamespace

import httpx
import pytest

from core import models
from crawlers import runner
from crawlers.board_state import board_outcome
from crawlers.greenhouse import GreenhouseAdapter
from crawlers.lever import LeverAdapter
from crawlers.ashby import AshbyAdapter
from crawlers.workable import WorkableAdapter
from crawlers.recruitee import RecruiteeAdapter
from crawlers.keka import KekaAdapter
from crawlers.smartrecruiters import SmartRecruitersAdapter


@pytest.fixture(
    params=[
        (GreenhouseAdapter, {"jobs": []}),
        (LeverAdapter, []),
        (AshbyAdapter, {"jobs": []}),
        (WorkableAdapter, {"jobs": []}),
        (RecruiteeAdapter, {"offers": []}),
        (KekaAdapter, []),
        (SmartRecruitersAdapter, {"content": [], "totalFound": 0}),
    ]
)
def board_adapter(request):
    adapter_class, empty_payload = request.param
    adapter = adapter_class(board_token="audit", company_name="Audit")
    yield adapter, empty_payload
    getattr(adapter, "_client", getattr(adapter, "client", None)).close()


def _stub_listing_api(
    monkeypatch, adapter, *, status=200, payload=None, malformed=False, timeout=False
):
    def get(url, **kwargs):
        request = httpx.Request("GET", url)
        if adapter.source_slug == "keka" and url.endswith("/careers/"):
            return httpx.Response(
                200, text="tenant 12345678-1234-1234-1234-123456789abc", request=request
            )
        if timeout:
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if malformed:
            return httpx.Response(status, text="not json", request=request)
        return httpx.Response(status, json=payload, request=request)

    monkeypatch.setattr(getattr(adapter, "_client", getattr(adapter, "client", None)), "get", get)


@pytest.mark.parametrize(
    "status,expected",
    [(200, "empty"), (404, "not_found"), (410, "not_found"), (429, "error"), (503, "error")],
)
def test_board_outcomes(board_adapter, monkeypatch, status, expected):
    adapter, payload = board_adapter
    _stub_listing_api(monkeypatch, adapter, status=status, payload=payload)
    assert adapter.fetch() == []
    assert board_outcome(adapter) == {"board_state": expected, "http_status": status}


@pytest.mark.parametrize("failure", ["malformed", "timeout", "shape"])
def test_errors_break_previous_empty_evidence(board_adapter, monkeypatch, failure):
    adapter, payload = board_adapter
    _stub_listing_api(monkeypatch, adapter, payload=payload)
    adapter.fetch()
    assert adapter.last_board_state == "empty"
    _stub_listing_api(
        monkeypatch,
        adapter,
        payload={"error": "unknown board"},
        malformed=failure == "malformed",
        timeout=failure == "timeout",
    )
    assert adapter.fetch() == []
    assert adapter.last_board_state == "error"
    assert adapter.last_http_status == (None if failure == "timeout" else 200)


def test_malformed_job_items_are_errors_not_empty_inventory(board_adapter, monkeypatch):
    adapter, payload = board_adapter
    if isinstance(payload, list):
        payload = [{}]
    else:
        payload = {key: ([{}] if isinstance(value, list) else 1) for key, value in payload.items()}
    _stub_listing_api(monkeypatch, adapter, payload=payload)
    assert adapter.fetch() == []
    assert adapter.last_board_state == "error"


class _Rows:
    def all(self):
        return []


class _MemorySession:
    def __init__(self):
        self.added = []

    def scalar(self, statement):
        return SimpleNamespace(last_content_hash="previously-populated")

    def scalars(self, statement):
        return _Rows()

    def add(self, row):
        self.added.append(row)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.mark.parametrize("prefetch", [False, True])
def test_empty_after_retry_is_partial_but_logs_definitive_evidence(monkeypatch, prefetch):
    class EmptyBoard:
        source_slug = "greenhouse"
        last_http_status = 200
        last_board_state = "empty"
        calls = 0

        def __init__(self, **kwargs):
            pass

        def fetch(self):
            type(self).calls += 1
            return []

        def health(self):
            return "ok"

    session = _MemorySession()
    kwargs = {}
    if prefetch:
        monkeypatch.setitem(runner.ATS_ADAPTERS, "greenhouse", EmptyBoard)
        job = runner._AtsJob(1, 1, "audit", "greenhouse", "audit", "Audit", True)
        board = runner._fetch_company_board(job)
        kwargs = dict(
            prefetched=board.listings,
            prefetched_health=board.health,
            prefetched_coverage=board.coverage,
        )
    result = runner.crawl_company_board(
        session,
        SimpleNamespace(id=1, crawl_tier=1, adapter_key="greenhouse"),
        SimpleNamespace(id=1, ats_board_id="audit", slug="audit", name="Audit"),
        EmptyBoard,
        **kwargs,
    )
    run = next(row for row in session.added if isinstance(row, models.CrawlRun))
    assert result["status"] == "partial"
    assert EmptyBoard.calls == 2
    assert run.log["board_state"] == "empty"
    assert run.log["board_token"] == "audit"
    assert run.log["http_status"] == 200
