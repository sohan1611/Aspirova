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

    assert result["status"] == "ok"
    assert result["notified"] == 501
    assert result["batches"] == 2
    assert [len(request["json"]["slugs"]) for request in requests] == [500, 1]
    assert {slug for request in requests for slug in request["json"]["slugs"]} == slugs
    assert all(request["timeout"] == revalidate.REQUEST_TIMEOUT_SECONDS for request in requests)
    assert all(
        request["headers"] == {"Authorization": "Bearer test-shared-secret"} for request in requests
    )


def test_notify_changed_skips_above_pathological_bound(monkeypatch) -> None:
    _configure(monkeypatch)

    def unexpected_post(*args, **kwargs):
        raise AssertionError("over-limit notification must not make an HTTP request")

    monkeypatch.setattr(revalidate.httpx, "post", unexpected_post)
    slugs = {f"opportunity-{index}" for index in range(revalidate.MAX_CHANGED_SLUGS + 1)}

    result = revalidate.notify_changed(slugs)

    assert result["status"] == "skipped_limit"
    assert result["changed"] == revalidate.MAX_CHANGED_SLUGS + 1
    assert result["notified"] == 0
    assert result["batches"] == 0
