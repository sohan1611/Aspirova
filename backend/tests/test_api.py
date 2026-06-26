"""Integration tests for the public read API against the real dev database
(Doc 02 sec 3 - feed/search/opportunity are public, no AI/heavy work on the
hot path). Bookmarks/auth are NOT tested here - blocked on SUPABASE_URL/
SUPABASE_ANON_KEY/SUPABASE_SERVICE_KEY, still blank in .env as of writing.

These tests read real crawled data (2,256+ opportunities seeded in Steps
6-7) rather than fixtures - there is no isolated test schema for the API
layer in Phase 1, so assertions are deliberately structural (shape, status
codes, ordering, pagination math) rather than asserting exact counts that
would break the moment the crawler runs again.
"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_feed_returns_paginated_active_opportunities() -> None:
    response = client.get("/feed", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert body["page"] == 1
    assert body["total"] > 0
    assert len(body["items"]) == 5
    item = body["items"][0]
    assert item["slug"]
    assert item["title"]


def test_feed_category_filter_only_returns_that_category() -> None:
    response = client.get("/feed", params={"category": "internship", "limit": 50})
    assert response.status_code == 200
    body = response.json()
    assert all(item["category"] == "internship" for item in body["items"])


def test_feed_remote_filter() -> None:
    response = client.get("/feed", params={"remote": True, "limit": 50})
    assert response.status_code == 200
    body = response.json()
    assert all(item["is_remote"] is True for item in body["items"])


def test_feed_invalid_category_rejected() -> None:
    response = client.get("/feed", params={"category": "not-a-real-category"})
    assert response.status_code == 422


def test_feed_pagination_pages_do_not_overlap() -> None:
    page1 = client.get("/feed", params={"page": 1, "limit": 10}).json()
    page2 = client.get("/feed", params={"page": 2, "limit": 10}).json()
    slugs1 = {item["slug"] for item in page1["items"]}
    slugs2 = {item["slug"] for item in page2["items"]}
    assert slugs1.isdisjoint(slugs2)
    assert page1["total"] == page2["total"]


def test_search_finds_real_results_and_total_matches_window_count() -> None:
    response = client.get("/search", params={"q": "software engineer", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert len(body["items"]) == 10


def test_search_typo_falls_back_to_trigram() -> None:
    response = client.get("/search", params={"q": "sofware enginer"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0  # FTS would not match this typo; only the fallback can


def test_search_truly_no_match_returns_empty_not_fallback_garbage() -> None:
    response = client.get("/search", params={"q": "zzzznonexistentqueryxyz123"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_search_deep_page_does_not_spuriously_trigger_fallback() -> None:
    """Regression test: an empty page > 1 must not be misread as 'zero FTS
    matches overall' (the window-function count only rides on returned
    rows, so an overshot offset comes back just as empty as a true zero
    match would) - see api/search.py."""
    shallow = client.get("/search", params={"q": "software engineer", "page": 1}).json()
    deep = client.get(
        "/search", params={"q": "software engineer", "page": 9999, "limit": 10}
    ).json()
    assert deep["items"] == []
    assert deep["total"] == shallow["total"]  # NOT silently re-counted via the trigram fallback


def test_opportunity_detail_by_real_slug() -> None:
    feed = client.get("/feed", params={"limit": 1}).json()
    slug = feed["items"][0]["slug"]

    response = client.get(f"/opportunity/{slug}")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == slug
    assert body["apply_url"].startswith("http")
    assert isinstance(body["description_raw"], str)


def test_opportunity_detail_404_for_unknown_slug() -> None:
    response = client.get("/opportunity/this-slug-does-not-exist-xyz")
    assert response.status_code == 404


def test_opportunity_outbound_link_is_the_real_source_not_aspirova() -> None:
    """Doc 01 sec 7 R1 / Doc 04 sec 10: link out, never mirror - the apply
    link must point at the source company's own site, not at us."""
    feed = client.get("/feed", params={"limit": 1}).json()
    slug = feed["items"][0]["slug"]
    body = client.get(f"/opportunity/{slug}").json()
    assert "aspirova" not in body["apply_url"].lower()
