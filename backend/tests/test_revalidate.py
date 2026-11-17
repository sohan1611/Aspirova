from types import SimpleNamespace

import httpx
import pytest

from core.config import Settings

import pipeline.revalidate as revalidate


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setattr(
        revalidate,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            api_base_url="https://api.example",
            revalidate_url="",
            revalidate_secret="",
        ),
    )


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("REVALIDATE_URL", "https://frontend.example/api/revalidate")
    monkeypatch.setenv("REVALIDATE_SECRET", "test-shared-secret")


def test_notify_changed_is_noop_when_configuration_is_absent(monkeypatch) -> None:
    monkeypatch.delenv("REVALIDATE_URL", raising=False)
    monkeypatch.delenv("REVALIDATE_SECRET", raising=False)

    def unexpected_post(*args, **kwargs):
        raise AssertionError("unconfigured notification must not make an HTTP request")

    monkeypatch.setattr(revalidate.httpx, "post", unexpected_post)

    result = revalidate.notify_changed({"software-engineer"})

    assert result["status"] == "unconfigured"
    assert result["notified"] == 0
    assert result["batches"] == 0


def test_notify_changed_does_not_raise_when_http_call_fails(monkeypatch) -> None:
    _configure(monkeypatch)

    def failing_post(*args, **kwargs):
        raise RuntimeError("frontend unavailable")

    monkeypatch.setattr(revalidate.httpx, "post", failing_post)

    result = revalidate.notify_changed({"software-engineer"})

    assert result["status"] == "failed"
    assert result["notified"] == 0
    assert result["failed_batches"] == 1


def test_notify_changed_batches_more_than_500_slugs(monkeypatch) -> None:
    _configure(monkeypatch)
    requests: list[dict] = []

    def recording_post(url, **kwargs):
        requests.append({"url": url, **kwargs})
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(revalidate.httpx, "post", recording_post)
    slugs = {f"opportunity-{index}" for index in range(501)}

    result = revalidate.notify_changed(slugs)

    # The landing-path request rides along on every configured call, so select the
    # slug batches rather than assuming they are the only requests made.
    slug_requests = [request for request in requests if "slugs" in request["json"]]

    assert result["status"] == "ok"
    assert result["notified"] == 501
    assert result["batches"] == 2
    assert [len(request["json"]["slugs"]) for request in slug_requests] == [500, 1]
    assert {slug for request in slug_requests for slug in request["json"]["slugs"]} == slugs
    assert all(request["timeout"] == revalidate.REQUEST_TIMEOUT_SECONDS for request in requests)
    assert all(
        request["headers"] == {"Authorization": "Bearer test-shared-secret"} for request in requests
    )


def test_notify_changed_revalidates_landing_paths(monkeypatch) -> None:
    _configure(monkeypatch)
    requests: list[dict] = []

    def recording_post(url, **kwargs):
        requests.append({"url": url, **kwargs})
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(revalidate.httpx, "post", recording_post)

    result = revalidate.notify_changed({"software-engineer"})

    path_requests = [request for request in requests if "paths" in request["json"]]

    assert len(path_requests) == 1
    assert path_requests[0]["json"]["paths"] == list(revalidate.LANDING_PATHS)
    assert path_requests[0]["headers"] == {"Authorization": "Bearer test-shared-secret"}
    assert result["paths_notified"] == len(revalidate.LANDING_PATHS)


def test_landing_paths_are_revalidated_even_when_no_slug_changed(monkeypatch) -> None:
    """A crawl changes what the lists show (counts, expiries) with no slug change."""
    _configure(monkeypatch)
    requests: list[dict] = []

    def recording_post(url, **kwargs):
        requests.append({"url": url, **kwargs})
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(revalidate.httpx, "post", recording_post)

    result = revalidate.notify_changed(set())

    assert result["status"] == "empty"
    assert result["notified"] == 0
    assert result["paths_notified"] == len(revalidate.LANDING_PATHS)
    assert [request["json"] for request in requests] == [{"paths": list(revalidate.LANDING_PATHS)}]


def test_landing_path_failure_does_not_break_slug_notification(monkeypatch) -> None:
    """Fail-open is per-request: a dead list push must not cost the slug batches."""
    _configure(monkeypatch)
    calls: list[dict] = []

    def flaky_post(url, **kwargs):
        calls.append(kwargs["json"])
        if "paths" in kwargs["json"]:
            raise RuntimeError("frontend unavailable")
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(revalidate.httpx, "post", flaky_post)

    result = revalidate.notify_changed({"software-engineer"})

    assert result["paths_notified"] == 0
    assert result["status"] == "ok"
    assert result["notified"] == 1


def test_notify_changed_skips_above_pathological_bound(monkeypatch) -> None:
    _configure(monkeypatch)
    requests: list[dict] = []

    # The bound guards against a pathological *slug* payload, not against the list
    # pages: a change that large is precisely when the lists are most stale, so the
    # landing-path request is still expected here. No slug batch may be sent.
    def recording_post(url, **kwargs):
        requests.append(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(revalidate.httpx, "post", recording_post)
    slugs = {f"opportunity-{index}" for index in range(revalidate.MAX_CHANGED_SLUGS + 1)}

    result = revalidate.notify_changed(slugs)

    assert requests == [{"paths": list(revalidate.LANDING_PATHS)}]
    assert result["status"] == "skipped_limit"
    assert result["changed"] == revalidate.MAX_CHANGED_SLUGS + 1
    assert result["notified"] == 0
    assert result["batches"] == 0


@pytest.mark.parametrize("slugs", [["software-engineer"], []])
def test_notify_changed_can_skip_landing_paths(monkeypatch, slugs):
    _configure(monkeypatch)
    requests = []
    monkeypatch.setattr(
        revalidate.httpx,
        "post",
        lambda url, **kw: (
            requests.append(kw["json"]) or SimpleNamespace(raise_for_status=lambda: None)
        ),
    )
    result = revalidate.notify_changed(slugs, landing=False)
    assert requests == ([{"slugs": slugs}] if slugs else [])
    assert result["paths_notified"] == 0
    assert result["status"] == ("ok" if slugs else "empty")


def test_refresh_api_details_validates_deduplicates_and_counts(monkeypatch):
    requests = []

    def get(url, **kwargs):
        requests.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(revalidate.httpx, "get", get)
    result = revalidate.refresh_api_details(
        [
            "role-1",
            "role-1",
            "role-2",
            "",
            None,
            [],
            123,
            "../feed",
            "UPPER",
            "-bad",
            "role/similar",
            "role?limit=10",
            "a" * 121,
        ]
    )
    assert result == {"status": "ok", "changed": 2, "refreshed": 2, "failed": 0, "invalid": 10}
    assert requests == [
        (
            f"https://api.example/opportunity/{slug}",
            {
                "headers": {"X-Aspirova-Refresh": "1"},
                "timeout": revalidate.API_REFRESH_TIMEOUT_SECONDS,
            },
        )
        for slug in ("role-1", "role-2")
    ]
    assert revalidate.API_REFRESH_TIMEOUT_SECONDS <= 5


@pytest.mark.parametrize("all_fail", [False, True])
def test_refresh_api_details_continues_after_http_errors(monkeypatch, all_fail):
    requests = []

    def get(url, **kwargs):
        requests.append(url)
        if url.endswith("role-1"):
            raise httpx.TimeoutException("test timeout")
        if all_fail:
            return httpx.Response(503, request=httpx.Request("GET", url))
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(revalidate.httpx, "get", get)
    result = revalidate.refresh_api_details(["role-1", "role-2"])
    assert len(requests) == 2
    assert result["failed"] == (2 if all_fail else 1)
    assert result["refreshed"] == (0 if all_fail else 1)
    assert result["status"] == ("failed" if all_fail else "partial")


def test_refresh_api_details_skips_empty_unconfigured_and_oversized_input(monkeypatch):
    monkeypatch.setattr(revalidate.httpx, "get", lambda *a, **kw: pytest.fail("Unexpected HTTP"))
    assert revalidate.refresh_api_details([])["status"] == "empty"
    assert (
        revalidate.refresh_api_details(
            [f"role-{i}" for i in range(revalidate.MAX_CHANGED_SLUGS + 1)]
        )["status"]
        == "skipped_limit"
    )
    monkeypatch.setattr(revalidate, "get_settings", lambda: SimpleNamespace(api_base_url=""))
    assert revalidate.refresh_api_details(["role"])["status"] == "unconfigured"


def test_refresh_api_details_never_raises_on_bad_iterable_or_configuration(monkeypatch):
    def broken():
        yield "role"
        raise RuntimeError("bad iterable")

    monkeypatch.setattr(revalidate.httpx, "get", lambda *a, **kw: pytest.fail("Unexpected HTTP"))
    assert revalidate.refresh_api_details(broken())["status"] == "collection_error"

    def settings():
        raise RuntimeError("bad configuration")

    monkeypatch.setattr(revalidate, "get_settings", settings)
    assert revalidate.refresh_api_details(["role"])["status"] == "configuration_error"


def test_notify_changed_loads_founder_dotenv_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("REVALIDATE_URL", raising=False)
    monkeypatch.delenv("REVALIDATE_SECRET", raising=False)
    config = tmp_path / "founder.env"
    config.write_text(
        "REVALIDATE_URL=https://frontend.example/api/revalidate\nREVALIDATE_SECRET=test-only\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=config)
    monkeypatch.setattr(revalidate, "get_settings", lambda: settings)
    requests = []
    monkeypatch.setattr(
        revalidate.httpx,
        "post",
        lambda url, **kw: (
            requests.append((url, kw)) or SimpleNamespace(raise_for_status=lambda: None)
        ),
    )
    result = revalidate.notify_changed(["role"], landing=False)
    assert result["status"] == "ok" and len(requests) == 1
    assert requests[0][0] == "https://frontend.example/api/revalidate"
    assert requests[0][1]["headers"] == {"Authorization": "Bearer test-only"}
