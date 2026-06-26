"""Tests for the bookmarks endpoints' unauthenticated path only. The
authenticated path (a real Supabase session) is NOT tested here - it is
blocked on SUPABASE_URL/SUPABASE_ANON_KEY, still blank in .env as of
writing. This file covers what's verifiable without those credentials:
the auth dependency must reject before ever reaching the network call.
"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_list_bookmarks_without_auth_header_returns_401() -> None:
    response = client.get("/bookmarks")
    assert response.status_code == 401


def test_add_bookmark_without_auth_header_returns_401() -> None:
    response = client.post("/bookmarks/some-slug")
    assert response.status_code == 401


def test_remove_bookmark_without_auth_header_returns_401() -> None:
    response = client.delete("/bookmarks/some-slug")
    assert response.status_code == 401


def test_malformed_auth_header_returns_401() -> None:
    response = client.get("/bookmarks", headers={"Authorization": "NotBearer something"})
    assert response.status_code == 401
