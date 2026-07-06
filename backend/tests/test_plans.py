"""GET /plans - public read for the pricing page (Doc handoffs/
PHASE-2.5-HANDOFF.md sec 3.7). Reads the real seeded rows (scripts/
seed_plans.py) rather than mocking, matching the rest of the suite."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_list_plans_returns_seeded_plans() -> None:
    response = client.get("/plans")
    assert response.status_code == 200

    plans = response.json()
    keys = {p["key"] for p in plans}
    assert {"free", "pro_lite_monthly", "pro_lite_annual", "pro_monthly", "pro_annual"} <= keys

    pro_annual = next(p for p in plans if p["key"] == "pro_annual")
    assert pro_annual["price_paise"] == 49900
    assert pro_annual["billing"] == "annual"
    assert pro_annual["features"]["copilot"] is True
