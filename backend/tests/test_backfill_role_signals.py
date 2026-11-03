"""Pure backfill transform coverage; never connects to a database."""

from copy import deepcopy

from scripts.backfill_role_signals import transform_row


def test_transform_preserves_unstop_pay_and_unrelated_fields():
    before = {
        "title": "Part-time Intern",
        "category": "internship",
        "country": "IN",
        "description_raw": "Stipend: ₹10,000/month\nDuration: 6 months\nPPO",
        "meta": {
            "compensation": {"unpaid": True, "source": "unstop"},
            "summary_source": "ai",
            "skills": ["Python"],
        },
        "summary": "Untouched",
        "closed_at": None,
    }
    snapshot = deepcopy(before)
    after = transform_row(before)
    assert after == {
        "meta": {**before["meta"], "duration_months": 6, "part_time": True, "job_offer": True}
    }
    assert before == snapshot
    assert transform_row({**before, **after}) == after


def test_transform_adds_pay_and_preserves_null_for_no_signal():
    assert transform_row({"category": "job", "meta": None}) == {"meta": None}
    after = transform_row({"category": "job", "description_raw": "Salary $130,000–150,000"})
    assert after == {
        "meta": {
            "compensation": {
                "min": 130000,
                "max": 150000,
                "currency": "USD",
                "period": "year",
                "source": "text",
            }
        }
    }
