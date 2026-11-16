"""Watch classification uses real models and calendar provenance without I/O."""

from datetime import date, datetime, timezone
import json

import pytest

from core.hiring_calendar import CALENDAR_META, IST, at_day, month_date, source_window
from core.models import Programme, ProgrammeEdition
from core.programme_watches import (
    classify_change,
    programme_change,
    programme_signature,
    programme_state,
)

NOW = datetime(2027, 1, 5, 12, tzinfo=IST)


def programme(*, status="expected", opening="2027-02-10", closing="2027-03-20"):
    return Programme(
        slug="test-watch-classification",
        name="Research programme",
        organiser="Institute",
        category="research_internship",
        url="https://example.edu/call",
        is_active=True,
        tags=[],
        editions=[
            ProgrammeEdition(
                year=2027,
                status=status,
                opens_at=at_day(date.fromisoformat(opening)) if opening else None,
                closes_at=at_day(date.fromisoformat(closing), end=True) if closing else None,
            )
        ],
    )


def test_identical_signatures_have_no_event():
    item = programme()
    signature = programme_signature(item, now=NOW)
    assert classify_change(signature, signature) is None
    assert programme_change(signature, item, now=NOW) is None


def test_tentative_month_shift_has_no_event():
    item = programme()
    before = programme_signature(item, now=NOW)
    item.editions[0].opens_at = month_date(2027, 3)
    item.editions[0].closes_at = month_date(2027, 4, end=True)
    after = programme_signature(item, now=NOW)
    assert before != after
    assert classify_change(before, after) is None


def test_added_next_cycle_projection_has_no_event():
    item = programme(status="closed")
    before = programme_signature(item, now=NOW)
    item.editions.append(
        ProgrammeEdition(
            year=2028,
            status="expected",
            opens_at=month_date(2028, 2),
            closes_at=month_date(2028, 3, end=True),
            notes="Projected next cycle from historical months.",
        )
    )
    assert classify_change(before, programme_signature(item, now=NOW)) is None


@pytest.mark.parametrize(
    "old_status,new_status,opening,expected",
    [
        ("expected", "announced", "2027-02-10", "announced"),
        ("expected", "open", "2027-01-01", "open"),
        ("announced", "open", "2027-01-01", "open"),
        ("open", "closed", "2027-01-01", "closed"),
        ("closed", "open", "2027-01-01", "open"),
    ],
)
def test_meaningful_status_changes(old_status, new_status, opening, expected):
    item = programme(status=old_status)
    before = programme_signature(item, now=NOW)
    item.editions[0].status = new_status
    item.editions[0].opens_at = at_day(date.fromisoformat(opening))
    assert classify_change(before, programme_signature(item, now=NOW)) == expected


@pytest.mark.parametrize(
    "old_deadline,new_deadline,expected",
    [
        (None, "2027-03-20", "deadline_set"),
        ("2027-03-20", "2027-03-21", "deadline_changed"),
        ("2027-03-20", "2027-03-19", "deadline_changed"),
        ("2027-03-20", None, "deadline_changed"),
    ],
)
def test_official_deadline_changes(old_deadline, new_deadline, expected):
    item = programme(status="announced", closing=old_deadline)
    before = programme_signature(item, now=NOW)
    item.editions[0].closes_at = (
        at_day(date.fromisoformat(new_deadline), end=True) if new_deadline else None
    )
    assert classify_change(before, programme_signature(item, now=NOW)) == expected


def test_elapsed_official_window_opens_and_closes_without_a_refresh_write():
    item = programme(status="announced", opening="2027-02-10", closing="2027-03-20")
    before = programme_signature(item, now=NOW)
    opened = programme_signature(item, now=datetime(2027, 2, 10, 12, tzinfo=IST))
    closed = programme_signature(item, now=datetime(2027, 3, 21, 12, tzinfo=IST))
    assert classify_change(before, opened) == "open"
    assert classify_change(opened, closed) == "closed"


def test_projection_does_not_hide_current_cycle_closure():
    item = programme(status="open", opening="2027-01-01", closing="2027-01-10")
    before = programme_signature(item, now=NOW)
    item.editions[0].status = "closed"
    item.editions.append(ProgrammeEdition(year=2028, status="expected"))
    change = programme_change(before, item, now=NOW)
    assert change["event"] == "closed"
    assert change["year"] == 2027
    assert len(json.loads(change["signature"])["windows"]) == 2


def test_tentative_downgrade_is_not_an_official_deadline_change():
    item = programme(status="announced")
    before = programme_signature(item, now=NOW)
    item.editions[0].status = "expected"
    assert classify_change(before, programme_signature(item, now=NOW)) is None


def test_verification_timestamp_and_wording_do_not_change_signature():
    item = programme(status="announced")
    before = programme_signature(item, now=NOW)
    item.editions[0].verified_at = NOW
    item.editions[0].notes = "Checked again; official page unchanged."
    assert programme_signature(item, now=NOW) == before


def test_timezone_storage_and_edition_order_do_not_change_signature():
    item = programme(status="announced")
    item.editions.append(ProgrammeEdition(year=2028, status="expected"))
    before = programme_signature(item, now=NOW)
    item.editions.reverse()
    edition = next(edition for edition in item.editions if edition.year == 2027)
    edition.opens_at = edition.opens_at.astimezone(timezone.utc)
    edition.closes_at = edition.closes_at.astimezone(timezone.utc)
    assert programme_signature(item, now=NOW) == before


def test_null_or_unknown_version_baseline_initializes_quietly():
    after = programme_signature(programme(status="announced"), now=NOW)
    for before in (None, "", "not-json", "[]", '{"version":999,"windows":[]}'):
        assert classify_change(before, after) is None


def test_month_precision_retains_only_month_in_signature():
    window = programme_state(programme(), now=NOW)["windows"][0]
    assert window["opens_at"] == "2027-02"
    assert window["closes_at"] == "2027-03"
    assert window["opens_precision"] == window["closes_precision"] == "month"


def test_synthetic_rolling_deadline_is_not_notified_as_a_deadline():
    item = programme(status="announced")
    item.editions[0].notes = "calendar_deadline_rolling"
    before = programme_signature(item, now=NOW)
    assert programme_state(item, now=NOW)["windows"][0]["closes_at"] is None
    item.editions[0].closes_at = month_date(2027, 4, end=True)
    assert classify_change(before, programme_signature(item, now=NOW)) is None
    item.editions[0].notes += "\ncalendar_exact_closes_at"
    assert classify_change(before, programme_signature(item, now=NOW)) == "deadline_set"


@pytest.mark.parametrize("slug", CALENDAR_META)
def test_every_authored_programme_has_a_stable_window_signature(slug):
    meta = CALENDAR_META[slug]
    window = source_window(slug)
    item = programme(status=window["status"])
    item.slug, item.name, item.organiser = slug, meta["name"], meta["organiser"]
    edition = item.editions[0]
    edition.year = meta["cycle_year"]
    edition.opens_at, edition.closes_at, edition.notes = (
        window["opens_at"],
        window["closes_at"],
        window["notes"],
    )
    signature = programme_signature(item, now=NOW)
    assert json.loads(signature)["windows"]
    assert classify_change(signature, programme_signature(item, now=NOW)) is None


def test_recurring_programme_advances_occurrence_without_projection_noise():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="announced")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]
    before = programme_signature(item, now=datetime(2027, 1, 31, 12, tzinfo=IST))
    change = programme_change(before, item, now=datetime(2027, 2, 1, 12, tzinfo=IST))
    assert change["event"] == "open"
    assert change["opens_at"] == "2027-02-01"
    assert len(json.loads(change["signature"])["windows"]) == 36


def test_recurring_year_boundary_opens_without_a_stored_next_year_edition():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="announced")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]
    before = programme_signature(item, now=datetime(2027, 12, 31, 12, tzinfo=IST))

    change = programme_change(before, item, now=datetime(2028, 1, 2, 12, tzinfo=IST))

    assert len(item.editions) == 1
    assert change["event"] == "open"
    assert change["year"] == 2028
    assert change["opens_at"] == "2028-01-01"


def test_adding_stored_recurring_projection_does_not_change_the_baseline():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="announced")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]
    before = programme_signature(item, now=NOW)
    item.editions.append(
        ProgrammeEdition(
            year=2028,
            status="expected",
            opens_at=month_date(2028, 1),
            closes_at=month_date(2028, 12, end=True),
            notes="Projected next cycle from historical months. Verify the new official call.",
        )
    )

    after = programme_signature(item, now=NOW)

    assert before == after
    assert classify_change(before, after) is None


def test_recurring_closure_is_not_hidden_when_a_projection_is_added():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="announced")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]
    before = programme_signature(item, now=NOW)
    item.editions.append(ProgrammeEdition(year=2028, status="expected"))

    change = programme_change(before, item, now=datetime(2027, 1, 11, 12, tzinfo=IST))

    assert change["event"] == "closed"
    assert change["closes_at"] == "2027-01-10"


def test_discontinued_recurring_programme_does_not_create_virtual_official_windows():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="discontinued")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]

    assert programme_state(item, now=NOW)["windows"] == []


def test_projected_recurring_edition_does_not_announce_standing_rule_again():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="announced")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]
    before = programme_signature(item, now=NOW)
    item.editions.append(
        ProgrammeEdition(
            year=2028,
            status="expected",
            notes="Projected next cycle from historical months. Verify the new official call.",
        )
    )
    after = programme_signature(item, now=NOW)
    assert before == after
    assert classify_change(before, after) is None


def test_standing_rule_opens_in_new_year_even_before_stored_edition_exists():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="announced")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]
    before = programme_signature(item, now=datetime(2027, 12, 31, 12, tzinfo=IST))
    change = programme_change(before, item, now=datetime(2028, 1, 2, 12, tzinfo=IST))
    assert change["event"] == "open"
    assert change["year"] == 2028
    assert change["opens_at"] == "2028-01-01"


def test_horizon_advances_without_announcing_the_new_future_year():
    meta = CALENDAR_META["niti-aayog-internship"]
    item = programme(status="announced")
    item.slug, item.name, item.organiser = "niti-aayog-internship", meta["name"], meta["organiser"]
    before = programme_state(item, now=datetime(2027, 12, 31, 12, tzinfo=IST))
    after = programme_state(item, now=datetime(2028, 1, 1, 12, tzinfo=IST))
    # Inspect just the newly introduced future-year windows: no announcement
    # should accompany the real current-year opening checked above.
    after["windows"] = [window for window in after["windows"] if window["year"] == 2029]
    assert classify_change(before, after) is None
