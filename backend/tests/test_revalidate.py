from types import SimpleNamespace

import pipeline.revalidate as revalidate


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
