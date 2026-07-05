"""Integration tests for the dream-companies API (Doc 03 sec 4.2) -
per-plan limits enforced entirely through can() (Doc 08 sec 1 hard rule).

Both get_db and get_current_user are overridden with the test's own
rollback-wrapped session/fake user (FastAPI's dependency_overrides), the
same pattern used to avoid a real Supabase session in test_bookmarks_auth.py
while still exercising the real route logic against real data.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded(db_session: Session):
    free_plan = models.Plan(
        key="free-dc-test",
        price_paise=0,
        billing=None,
        features={"dream_companies_limit": 1},
    )
    pro_plan = models.Plan(
        key="pro-dc-test",
        price_paise=4900,
        billing="monthly",
        features={"dream_companies_limit": None},
    )
    user = models.User(email=f"dream-companies-test-{uuid.uuid4()}@example.com")
    company_a = models.Company(slug="dc-test-acme", name="Acme", name_normalized="acme")
    company_b = models.Company(slug="dc-test-globex", name="Globex", name_normalized="globex")
    db_session.add_all([free_plan, pro_plan, user, company_a, company_b])
    db_session.flush()
    return {
        "free_plan": free_plan,
        "pro_plan": pro_plan,
        "user": user,
        "company_a": company_a,
        "company_b": company_b,
    }


@pytest.fixture
def client(db_session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_free_user_can_add_one_dream_company(client, seeded) -> None:
    response = client.post(f"/dream-companies/{seeded['company_a'].slug}")
    assert response.status_code == 204

    listed = client.get("/dream-companies").json()
    assert len(listed) == 1
    assert listed[0]["company"]["slug"] == seeded["company_a"].slug


def test_free_user_is_blocked_at_the_second_dream_company(client, seeded, db_session) -> None:
    client.post(f"/dream-companies/{seeded['company_a'].slug}")

    response = client.post(f"/dream-companies/{seeded['company_b'].slug}")

    assert response.status_code == 403
    listed = client.get("/dream-companies").json()
    assert len(listed) == 1


def test_pro_user_is_not_limited(client, seeded, db_session) -> None:
    db_session.add(
        models.Subscription(
            user_id=seeded["user"].id, plan_id=seeded["pro_plan"].id, status="active"
        )
    )
    db_session.flush()

    r1 = client.post(f"/dream-companies/{seeded['company_a'].slug}")
    r2 = client.post(f"/dream-companies/{seeded['company_b'].slug}")

    assert r1.status_code == 204
    assert r2.status_code == 204
    assert len(client.get("/dream-companies").json()) == 2


def test_adding_the_same_company_twice_is_idempotent_not_a_limit_violation(client, seeded) -> None:
    r1 = client.post(f"/dream-companies/{seeded['company_a'].slug}")
    r2 = client.post(f"/dream-companies/{seeded['company_a'].slug}")

    assert r1.status_code == 204
    assert (
        r2.status_code == 204
    )  # re-adding the same one already at the limit is a no-op, not a 403
    assert len(client.get("/dream-companies").json()) == 1


def test_removing_a_dream_company_frees_up_the_limit(client, seeded) -> None:
    client.post(f"/dream-companies/{seeded['company_a'].slug}")

    remove_response = client.delete(f"/dream-companies/{seeded['company_a'].slug}")
    add_other_response = client.post(f"/dream-companies/{seeded['company_b'].slug}")

    assert remove_response.status_code == 204
    assert add_other_response.status_code == 204
    listed = client.get("/dream-companies").json()
    assert len(listed) == 1
    assert listed[0]["company"]["slug"] == seeded["company_b"].slug


def test_unknown_company_slug_returns_404(client) -> None:
    response = client.post("/dream-companies/this-company-does-not-exist-xyz")
    assert response.status_code == 404
