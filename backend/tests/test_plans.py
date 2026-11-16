"""GET /plans - public read for the pricing page (Doc handoffs/
PHASE-2.5-HANDOFF.md sec 3.7). Reads the real seeded rows (scripts/
seed_plans.py) rather than mocking, matching the rest of the suite."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.main import app
from core import models
from core.plans import RETIRED_PLAN_KEYS
from scripts.seed_plans import PLANS

client = TestClient(app)


def test_list_plans_returns_seeded_plans() -> None:
    response = client.get("/plans")
    assert response.status_code == 200

    plans = response.json()
    keys = {p["key"] for p in plans}
    assert {"free", "pro_lite_monthly", "pro_monthly", "pro_annual"} <= keys
    assert keys.isdisjoint(RETIRED_PLAN_KEYS)

    pro_annual = next(p for p in plans if p["key"] == "pro_annual")
    assert pro_annual["price_paise"] == 49900
    assert pro_annual["billing"] == "annual"
    assert pro_annual["features"]["copilot"] is True


def test_retired_plan_stays_seeded_but_is_not_offered(engine) -> None:
    retired_seed = next(plan for plan in PLANS if plan[0] == "pro_lite_annual")
    assert retired_seed[1:3] == (39900, "annual")
    with Session(engine) as db:
        retired = db.scalar(select(models.Plan).where(models.Plan.key == "pro_lite_annual"))
        assert retired is not None
        assert retired.price_paise == 39900
        assert retired.billing == "annual"

    response = client.get("/plans")
    assert response.status_code == 200
    assert "pro_lite_annual" not in {plan["key"] for plan in response.json()}
