"""Unit test for the pure board-fingerprint helper (no DB/network)."""

from core.adapters import RawListing
from crawlers.runner import _board_fingerprint


def _listing(external_id: str, content_hash: str) -> RawListing:
    return RawListing(
        source_slug="greenhouse",
        external_id=external_id,
        source_url=f"https://example.test/{external_id}",
        content_hash=content_hash,
        raw_payload={},
    )


def test_fingerprint_stable_regardless_of_input_order() -> None:
    a = [_listing("1", "h1"), _listing("2", "h2")]
    b = [_listing("2", "h2"), _listing("1", "h1")]
    assert _board_fingerprint(a) == _board_fingerprint(b)


def test_fingerprint_changes_when_a_job_is_updated() -> None:
    before = [_listing("1", "h1"), _listing("2", "h2")]
    after = [_listing("1", "h1"), _listing("2", "h2-updated")]
    assert _board_fingerprint(before) != _board_fingerprint(after)


def test_fingerprint_changes_when_a_job_is_added() -> None:
    before = [_listing("1", "h1")]
    after = [_listing("1", "h1"), _listing("2", "h2")]
    assert _board_fingerprint(before) != _board_fingerprint(after)


def test_fingerprint_empty_list_is_deterministic() -> None:
    assert _board_fingerprint([]) == _board_fingerprint([])
