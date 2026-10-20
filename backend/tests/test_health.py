from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health(monkeypatch) -> None:
    monkeypatch.setattr("api.main.key_fingerprint", lambda: "0123456789ab")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["unsubscribe_key"] == "0123456789ab"
