"""Offline pass/fail cases; these tests never request a browser or database."""

from copy import deepcopy

import pytest

from calendar_coverage import assert_calendar_coverage


def healthy() -> dict:
    return {
        "source_rows": 10,
        "published_dated": 2,
        "published_rolling": 1,
        "outside_window": 2,
        "closed": 1,
        "retired": 1,
        "skipped": [{"row_id": "8", "slug": "skip", "reason": "category"}],
        "pending_import": [
            {"row_id": "9", "slug": "pending"},
            {"row_id": "10", "slug": "pending-too"},
        ],
        "unexplained": [],
        "published_total": 3,
        "rows_without_metadata": 0,
        "metadata_without_row": 0,
    }


def test_pending_import_is_allowed() -> None:
    assert_calendar_coverage(healthy(), 10)


@pytest.mark.parametrize(
    "change",
    [
        {"source_rows": 11},
        {"unexplained": [{"row_id": "bad", "slug": "bad"}]},
        {"rows_without_metadata": 1},
        {"metadata_without_row": 1},
        {"retired": 2},
        {"published_total": 4},
        {
            "published_dated": 0,
            "published_rolling": 0,
            "published_total": 0,
            "retired": 4,
        },
        {"published_dated": -1},
        {"published_dated": True},
        {"skipped": 1},
    ],
)
def test_bad_coverage_fails_with_pending_context(change: dict) -> None:
    coverage = deepcopy(healthy())
    coverage.update(change)
    with pytest.raises(AssertionError, match="pending_import"):
        assert_calendar_coverage(coverage, 10)


def test_checkout_count_must_match() -> None:
    with pytest.raises(AssertionError, match="Deployed JSON has 12 rows"):
        assert_calendar_coverage(healthy(), 12)
