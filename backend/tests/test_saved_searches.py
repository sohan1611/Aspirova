"""Integration tests for authenticated saved-search endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from api.saved_searches import enforce_saved_search_write_limit
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
    suffix = str(uuid.uuid4())
    user = models.User(email=f"saved-search-test-{suffix}@example.com")
    other_user = models.User(email=f"saved-search-other-{suffix}@example.com")
    db_session.add_all([user, other_user])
    db_session.flush()
    return {"user": user, "other_user": other_user}


@pytest.fixture
def client(db_session: Session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    app.dependency_overrides[enforce_saved_search_write_limit] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(enforce_saved_search_write_limit, None)


def test_create_saved_search_persists_params(client, db_session, seeded) -> None:
    response = client.post(
        "/saved-searches",
        json={
            "name": "Early internships in India",
            "params": {
                "q": "software engineer",
                "category": "internship",
                "country": "IN",
                "experience": "early",
            },
        },
    )

    assert response.status_code == 200
    item = response.json()
    assert item["name"] == "Early internships in India"
    assert item["params"]["q"] == "software engineer"
    assert item["params"]["category"] == "internship"
    assert item["params"]["country"] == "IN"
    assert item["params"]["experience"] == "early"
    assert item["alerts_enabled"] is True

    saved_search = db_session.get(models.SavedSearch, item["id"])
    assert saved_search is not None
    assert saved_search.user_id == seeded["user"].id
    assert saved_search.params == {
        "q": "software engineer",
        "category": "internship",
        "country": "IN",
        "experience": "early",
    }


def test_list_saved_searches_hides_other_users_rows(client, db_session, seeded) -> None:
    mine = models.SavedSearch(
        user_id=seeded["user"].id,
        name="My search",
        params={"category": "internship"},
    )
    someone_elses = models.SavedSearch(
        user_id=seeded["other_user"].id,
        name="Other search",
        params={"category": "job"},
    )
    db_session.add_all([mine, someone_elses])
    db_session.flush()

    response = client.get("/saved-searches")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [mine.id]


def test_delete_saved_search_is_user_scoped(client, db_session, seeded) -> None:
    mine = models.SavedSearch(user_id=seeded["user"].id, params={"category": "internship"})
    someone_elses = models.SavedSearch(
        user_id=seeded["other_user"].id,
        params={"category": "job"},
    )
    db_session.add_all([mine, someone_elses])
    db_session.flush()
    mine_id = mine.id
    someone_elses_id = someone_elses.id

    response = client.delete(f"/saved-searches/{mine_id}")

    assert response.status_code == 204
    saved_search = db_session.scalar(
        select(models.SavedSearch).where(models.SavedSearch.id == mine_id)
    )
    assert saved_search is None

    response = client.delete(f"/saved-searches/{someone_elses_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Saved search not found"


def test_patch_saved_search_alerts_is_user_scoped(client, db_session, seeded) -> None:
    mine = models.SavedSearch(
        user_id=seeded["user"].id,
        params={"category": "internship"},
        alerts_enabled=True,
    )
    someone_elses = models.SavedSearch(
        user_id=seeded["other_user"].id,
        params={"category": "job"},
    )
    db_session.add_all([mine, someone_elses])
    db_session.flush()
    mine_id = mine.id
    someone_elses_id = someone_elses.id

    response = client.patch(f"/saved-searches/{mine_id}", json={"alerts_enabled": False})

    assert response.status_code == 200
    assert response.json()["alerts_enabled"] is False
    db_session.refresh(mine)
    assert mine.alerts_enabled is False

    response = client.patch(f"/saved-searches/{someone_elses_id}", json={"alerts_enabled": False})

    assert response.status_code == 404


def test_saved_search_cap_is_enforced(client, db_session, seeded) -> None:
    db_session.add_all(
        [
            models.SavedSearch(user_id=seeded["user"].id, params={"q": f"search {index}"})
            for index in range(25)
        ]
    )
    db_session.flush()

    response = client.post("/saved-searches", json={"params": {"category": "internship"}})

    assert response.status_code == 409
    assert response.json()["detail"] == "Saved search limit of 25 reached"


def test_saved_searches_require_auth() -> None:
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as unauthenticated_client:
            response = unauthenticated_client.get("/saved-searches")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"category": "fellowship"},
        {"country": "IND"},
        {"country": "1!"},
        {"q": "x" * 201},
        {"unknown_filter": "value"},
    ],
)
def test_invalid_saved_search_params_return_422(client, params) -> None:
    response = client.post("/saved-searches", json={"params": params})

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("experience", "new_grad"),
        ("location", ["Bangalore", "Bengaluru"]),
        ("role", "software"),
        ("paid", True),
        ("paid", False),
        ("min_stipend", 10000),
        ("part_time", True),
        ("part_time", False),
        ("max_duration", 6),
        ("job_offer", True),
        ("job_offer", False),
        ("comp_type", ["case_competition", "hiring_challenge"]),
        ("registration", "free"),
        ("deadline_within", 7),
        ("organiser_type", ["iit", "other"]),
        ("mode", ["online", "hybrid"]),
        ("prize_min", 0),
        ("status", "open"),
        ("status", "closed"),
    ],
)
def test_new_saved_search_params_round_trip(client, db_session, key, value) -> None:
    params = {key: value}
    response = client.post("/saved-searches", json={"params": params})
    assert response.status_code == 200
    item = response.json()
    assert item["params"] == params
    stored = db_session.get(models.SavedSearch, item["id"])
    assert stored.params == params
    loaded = next(row for row in client.get("/saved-searches").json() if row["id"] == item["id"])
    assert loaded["params"] == params


@pytest.mark.parametrize(
    "params",
    [
        {"location": ["x"] * 6},
        {"location": ["x" * 81]},
        {"location": "Bangalore"},
        {"role": "unknown"},
        {"paid": "maybe"},
        {"part_time": "maybe"},
        {"job_offer": "maybe"},
        {"min_stipend": -1},
        {"max_duration": 0},
        {"max_duration": 25},
        {"comp_type": ["unknown"]},
        {"comp_type": ["case_competition", "unknown"]},
        {"registration": "unknown"},
        {"deadline_within": 2},
        {"organiser_type": ["unknown"]},
        {"mode": ["unknown"]},
        {"prize_min": -1},
        {"status": "active"},
    ],
)
def test_new_saved_search_params_are_validated(client, params) -> None:
    assert client.post("/saved-searches", json={"params": params}).status_code == 422


def test_existing_saved_search_rows_still_load(client, db_session, seeded) -> None:
    row = models.SavedSearch(
        user_id=seeded["user"].id,
        params={"q": "software", "category": "internship", "remote": False},
    )
    db_session.add(row)
    db_session.flush()
    response = client.get("/saved-searches")
    assert response.status_code == 200
    loaded = next(item for item in response.json() if item["id"] == row.id)
    assert loaded["params"] == row.params


@pytest.mark.parametrize(
    ("name", "expected"), [("  New name  ", "New name"), (None, None), ("   ", None)]
)
def test_patch_saved_search_name(client, db_session, seeded, name, expected) -> None:
    row = models.SavedSearch(user_id=seeded["user"].id, name="Old name", params={"q": "python"})
    db_session.add(row)
    db_session.flush()

    response = client.patch(f"/saved-searches/{row.id}", json={"name": name})

    assert response.status_code == 200
    assert response.json()["name"] == expected
    assert response.json()["params"] == {"q": "python"}
    db_session.refresh(row)
    assert row.name == expected


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"unknown": True},
        {"name": "x" * 81},
        {"params": None},
        {"params": {"category": "invalid"}},
        {"params": {"country": "IND"}},
        {"params": {"role": "unknown"}},
        {"params": {"editSearch": "1"}},
        {"params": {"min_stipend": -1}},
        {"alerts_enabled": None},
    ],
)
def test_invalid_saved_search_patch_returns_422(client, db_session, seeded, patch) -> None:
    row = models.SavedSearch(user_id=seeded["user"].id, params={"q": "python"})
    db_session.add(row)
    db_session.flush()

    assert client.patch(f"/saved-searches/{row.id}", json=patch).status_code == 422
    db_session.refresh(row)
    assert row.params == {"q": "python"}


@pytest.mark.parametrize(
    "patch",
    [
        {"name": "Renamed"},
        {"name": None},
        {"name": "   "},
        {"params": {"q": "python"}},
        {"alerts_enabled": False},
        {"name": "Combined", "params": {"q": "python"}, "alerts_enabled": True},
        {"params": {}},
        {"params": None},
    ],
)
def test_each_saved_search_patch_is_user_scoped(client, db_session, seeded, patch) -> None:
    row = models.SavedSearch(
        user_id=seeded["other_user"].id,
        name="Private search",
        params={"q": "private"},
    )
    db_session.add(row)
    db_session.flush()

    assert client.patch(f"/saved-searches/{row.id}", json=patch).status_code == 404
    db_session.refresh(row)
    assert row.name == "Private search"
    assert row.params == {"q": "private"}
    assert row.alerts_enabled is True


@pytest.mark.parametrize("previously_alerted", [False, True])
def test_filter_edit_resets_alert_baseline(client, db_session, seeded, previously_alerted) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=7)
    row = models.SavedSearch(
        user_id=seeded["user"].id,
        name="Keep my name",
        params={"q": "python"},
        created_at=old,
        last_alerted_at=old if previously_alerted else None,
    )
    db_session.add(row)
    db_session.flush()
    before = datetime.now(timezone.utc)

    response = client.patch(
        f"/saved-searches/{row.id}",
        json={"params": {"q": "design", "registration": " FREE "}},
    )
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    db_session.refresh(row)
    assert before <= row.last_alerted_at <= after
    assert row.params == {"q": "design", "registration": "free"}
    assert row.name == "Keep my name"
    assert row.created_at == old


@pytest.mark.parametrize("previously_alerted", [False, True])
@pytest.mark.parametrize(
    "patch",
    [
        {"params": {"registration": " FREE ", "q": "python"}},
        {"name": "New name"},
        {"alerts_enabled": False},
    ],
)
def test_non_filter_edits_preserve_alert_baseline(
    client,
    db_session,
    seeded,
    patch,
    previously_alerted,
) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=7)
    baseline = old if previously_alerted else None
    row = models.SavedSearch(
        user_id=seeded["user"].id,
        name="Original name",
        params={"q": "python", "registration": "free"},
        last_alerted_at=baseline,
    )
    db_session.add(row)
    db_session.flush()

    response = client.patch(f"/saved-searches/{row.id}", json=patch)

    assert response.status_code == 200
    db_session.refresh(row)
    assert row.last_alerted_at == baseline
    assert row.params == {"q": "python", "registration": "free"}
    if "name" not in patch:
        assert row.name == "Original name"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": None},
        {"q": ""},
        {"q": "   "},
        {"location": []},
        {"location": ["  "]},
        {"comp_type": []},
        {"organiser_type": []},
        {"mode": []},
    ],
)
def test_patch_saved_search_requires_at_least_one_filter(
    client, db_session, seeded, params
) -> None:
    baseline = datetime.now(timezone.utc) - timedelta(days=7)
    row = models.SavedSearch(
        user_id=seeded["user"].id,
        name="Original name",
        params={"q": "python"},
        last_alerted_at=baseline,
    )
    db_session.add(row)
    db_session.flush()

    response = client.patch(
        f"/saved-searches/{row.id}",
        json={"name": "Should not save", "params": params},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "A saved search needs at least one filter"
    db_session.refresh(row)
    assert row.name == "Original name"
    assert row.params == {"q": "python"}
    assert row.last_alerted_at == baseline


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": None},
        {"q": ""},
        {"q": "   "},
        {"location": []},
        {"location": ["  "]},
        {"comp_type": []},
        {"organiser_type": []},
        {"mode": []},
    ],
)
def test_create_saved_search_requires_at_least_one_filter(client, db_session, params) -> None:
    before = set(db_session.scalars(select(models.SavedSearch.id)).all())

    response = client.post("/saved-searches", json={"params": params})

    assert response.status_code == 422
    assert response.json()["detail"] == "A saved search needs at least one filter"
    assert set(db_session.scalars(select(models.SavedSearch.id)).all()) == before


@pytest.mark.parametrize(
    "params",
    [
        {"remote": False},
        {"paid": False},
        {"part_time": False},
        {"job_offer": False},
        {"min_stipend": 0},
        {"prize_min": 0},
    ],
)
def test_create_saved_search_preserves_falsy_filters(client, db_session, params) -> None:
    response = client.post("/saved-searches", json={"params": params})

    assert response.status_code == 200
    assert response.json()["params"] == params
    row = db_session.get(models.SavedSearch, response.json()["id"])
    assert row.params == params


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"q": "  python  "}, {"q": "python"}),
        ({"location": ["Bengaluru, India", " "]}, {"location": ["Bengaluru, India"]}),
    ],
)
def test_create_saved_search_cleans_filters(client, db_session, params, expected) -> None:
    response = client.post("/saved-searches", json={"params": params})

    assert response.status_code == 200
    assert response.json()["params"] == expected
    row = db_session.get(models.SavedSearch, response.json()["id"])
    assert row.params == expected


@pytest.mark.parametrize("patch", [{"name": "Renamed"}, {"alerts_enabled": False}])
def test_empty_saved_search_still_lists_and_accepts_non_filter_edits(
    client, db_session, seeded, patch
) -> None:
    baseline = datetime.now(timezone.utc) - timedelta(days=7)
    row = models.SavedSearch(
        user_id=seeded["user"].id,
        name="Legacy search",
        params={},
        last_alerted_at=baseline,
    )
    db_session.add(row)
    db_session.flush()

    response = client.get("/saved-searches")

    assert response.status_code == 200
    loaded = next(item for item in response.json() if item["id"] == row.id)
    assert loaded["params"] == {}

    response = client.patch(f"/saved-searches/{row.id}", json=patch)

    assert response.status_code == 200
    for key, value in patch.items():
        assert response.json()[key] == value
    db_session.refresh(row)
    assert row.params == {}
    assert row.last_alerted_at == baseline
    for key, value in patch.items():
        assert getattr(row, key) == value
