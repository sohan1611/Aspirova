"""Pure row-transform tests; no database or source calls."""

from copy import deepcopy

import pytest

from scripts.backfill_unstop_fields import transform_row


@pytest.mark.parametrize("work_mode, expected_remote", [("in_office", False), ("wfh", True)])
def test_transform_recomputes_role_fields_and_preserves_other_data(
    work_mode: str,
    expected_remote: bool,
) -> None:
    before = {
        "location": "Online",
        "country": None,
        "is_remote": True,
        "meta": {"skills": ["Python"], "summary_source": "deterministic", "timing": "old"},
        "summary": "Keep this summary",
        "closed_at": "closed",
        "deadline": "future",
    }
    snapshot = deepcopy(before)
    payload = {
        "_aspirova_opportunity": "internships",
        "region": "online",
        "jobDetail": {
            "type": work_mode,
            "timing": "full_time",
            "paid_unpaid": "unpaid",
            "locations": ["Bangalore", "Hyderabad"],
        },
    }
    after = transform_row(before, payload)
    assert after == {
        "location": "Bangalore; Hyderabad",
        "country": "IN",
        "is_remote": expected_remote,
        "meta": {
            "skills": ["Python"],
            "summary_source": "deterministic",
            "timing": "full_time",
            "work_mode": work_mode,
            "compensation": {"unpaid": True, "source": "unstop"},
        },
    }
    assert before == snapshot
    assert transform_row(after, payload) == after


def test_transform_removes_stale_pay_and_work_metadata_only() -> None:
    before = {"meta": {"compensation": {"unpaid": True}, "work_mode": "wfh", "skills": ["SQL"]}}
    after = transform_row(before, {"jobDetail": {"type": "in_office", "show_salary": 0}})
    assert after == {
        "location": None,
        "country": "IN",
        "is_remote": False,
        "meta": {"skills": ["SQL"], "work_mode": "in_office"},
    }


def test_transform_keeps_pay_parsed_from_listing_text() -> None:
    # Real row: Ganexis Global's ₹20,000 came from its description, and Unstop's
    # own salary field is hidden. An earlier version of this backfill erased it.
    pay = {"min": 20000, "max": 20000, "currency": "INR", "period": "month", "source": "text"}
    after = transform_row(
        {"meta": {"compensation": pay}},
        {"jobDetail": {"type": "in_office", "paid_unpaid": "paid", "show_salary": 0}},
    )
    assert after["meta"]["compensation"] == pay


def test_transform_lets_unstop_pay_replace_pay_parsed_from_text() -> None:
    after = transform_row(
        {"meta": {"compensation": {"min": 1, "max": 1, "source": "text"}}},
        {"jobDetail": {"paid_unpaid": "unpaid"}},
    )
    assert after["meta"]["compensation"] == {"unpaid": True, "source": "unstop"}


def test_transform_foreign_country_uses_location_inference() -> None:
    after = transform_row(
        {},
        {
            "jobDetail": {"type": "in_office", "locations": ["Berlin"]},
            "locations": [{"city": "Berlin", "country": "Germany"}],
        },
    )
    assert after["country"] == "DE"
