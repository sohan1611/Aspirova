import inspect

from fastapi.testclient import TestClient

from api.main import app, health

client = TestClient(app)


def test_health(monkeypatch) -> None:
    monkeypatch.setattr("api.main.key_fingerprint", lambda: "0123456789ab")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["unsubscribe_key"] == "0123456789ab"


def test_health_never_waits_for_a_worker_thread() -> None:
    """Render restarts the instance when /health misses its 5 s check (2026-11-10).

    A sync handler queues for the same thread pool that a burst of requests fills
    while each waits for a DB connection, so /health must stay a coroutine with no I/O.
    """
    assert inspect.iscoroutinefunction(health)
