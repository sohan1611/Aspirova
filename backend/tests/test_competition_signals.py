from copy import deepcopy

import pytest

from core.adapters import NormalizedListing
from pipeline.competition_signals import merge_competition_signals, prize_pool_inr
from pipeline.ingest import _listing_meta


@pytest.mark.parametrize(
    "meta, expected",
    [
        ({"prize": "$0"}, None),
        ({"prize": "$1,000"}, 88000),
        ({"prize": "₹20,000"}, 20000),
        ({"prize": "€8,000"}, 800000),
        ({"prize": "CA$500"}, 31500),
        ({"prize": "C$500"}, 31500),
        ({"prize": "A$500"}, 28500),
        ({"prize": "S$500"}, 33500),
        ({"prize": "£500"}, 57500),
        ({"prize": " INR 1,000 "}, 1000),
        ({"prize": "USD 500"}, 44000),
        ({"prize": "EUR 500"}, 50000),
        ({"prize": "GBP 500"}, 57500),
        ({"prize": "Fiji"}, None),
        ({"prize": None}, None),
        (None, None),
        ({"prize": "1000"}, None),
        ({"prizes": [{"cash": "1000", "currency": "fa-dollar"}]}, 88000),
        ({"prizes": [{"cash": "1e3", "currency": "USD"}]}, 88000),
        ({"prizes": [{"cash": "+1000", "currency": "USD"}]}, 88000),
        ({"prizes": [{"cash": None, "currency": "INR"}]}, None),
        ({"prizes": [{"cash": 1000, "currency": "unknown"}]}, None),
        ({"prizes": [{"cash": True, "currency": "INR"}]}, None),
        ({"prizes": [{"cash": False, "currency": "INR"}]}, None),
        ({"prizes": [{"cash": -1, "currency": "INR"}]}, None),
        ({"prizes": [{"cash": "NaN", "currency": "INR"}]}, None),
        ({"prizes": [{"cash": float("inf"), "currency": "INR"}]}, None),
        ({"prizes": [{"cash": 0.75, "currency": "INR"}]}, 1),
        ({"prizes": [{"cash": 100, "currency": "INR"}], "prize": "$1,000"}, 100),
        ({"prizes": [{"cash": None, "currency": "INR"}], "prize": "$1,000"}, 88000),
        (
            {
                "prizes": [
                    {"cash": 100, "currency": "fa-rupee"},
                    {"cash": "10", "currency": "fa-usd"},
                    {"cash": 2, "currency": "fa-eur"},
                    {"cash": 1, "currency": "fa-gbp"},
                    {"cash": None, "currency": "INR"},
                    {"cash": 10000, "currency": "unknown"},
                ]
            },
            1295,
        ),
    ],
)
def test_prize_pool_inr(meta, expected):
    assert prize_pool_inr(meta) == expected


@pytest.mark.parametrize("token", ["fa-rupee", "fa-inr", "fa-rupee-sign", "INR", "inr"])
def test_existing_rupee_tokens(token):
    assert prize_pool_inr({"prizes": [{"cash": 1000, "currency": token}]}) == 1000


@pytest.mark.parametrize("category", ["hackathon", "competition", "scholarship"])
def test_merge_removes_stale_signal_without_mutating_metadata(category):
    meta = {"prize": "$0", "prize_inr": 88000, "prize_text": "$1,000", "skills": ["Python"]}
    before = deepcopy(meta)
    assert merge_competition_signals(meta, category) == {"prize": "$0", "skills": ["Python"]}
    assert meta == before
    assert merge_competition_signals({"prize": "$1,000"}, category)["prize_inr"] == 88000


def test_other_categories_keep_their_metadata():
    meta = {"prize_inr": 123, "prize_text": "$1,000", "prize": "$0"}
    assert merge_competition_signals(meta, "job") == meta


@pytest.mark.parametrize("category", ["hackathon", "competition", "scholarship"])
def test_ingest_metadata_includes_competition_signals(category):
    listing = NormalizedListing(
        source_slug="devpost",
        external_id="example",
        source_url="https://example.com/event",
        title="Example event",
        company_name="Example",
        category=category,
        description_raw="",
        apply_url="https://example.com/event",
        meta={"prize": "$1,000"},
    )
    assert _listing_meta(listing, None) == {
        "prize": "$1,000",
        "prize_inr": 88000,
        "prize_text": "$1,000",
    }


def test_stated_pool_is_not_added_to_its_component_prizes():
    meta = {
        "prizes": [
            {
                "rank": "Prize pool across 21 innovation tracks...",
                "cash": 10500000,
                "currency": "INR",
            },
            {
                "rank": "Top 3 winners in every track: 1st Prize",
                "cash": 250000,
                "currency": "INR",
            },
            {
                "rank": "Top 3 winners in every track: 2nd Prize",
                "cash": 150000,
                "currency": "INR",
            },
        ]
    }
    result = merge_competition_signals(meta, "competition")
    assert result["prize_inr"] == 10500000
    assert result["prize_text"] == "₹1,05,00,000"
    assert result["prizes"] == meta["prizes"]


@pytest.mark.parametrize(
    "label", ["Prize pool", "Total", "Overall Prize Bucket", "Prize bucket", "Prizes worth"]
)
def test_largest_stated_pool_wins(label):
    meta = {
        "prizes": [
            {"rank": label, "cash": 110000, "currency": "INR"},
            {"rank": "TOTAL", "cash": 2000, "currency": "USD"},
            {"rank": "Winner First Prize", "cash": 500000, "currency": "INR"},
            {"rank": "Total credits", "cash": 1000000, "currency": "USD"},
        ]
    }
    result = merge_competition_signals(meta, "competition")
    assert result["prize_inr"] == 176000
    assert result["prize_text"] == "$2,000"


def test_overall_challenge_winners_are_not_a_stated_pool():
    meta = {
        "prizes": [
            {"rank": "Top 5 Overall Challenge Winners", "cash": 3500, "currency": "INR"},
            {"rank": "Second Prize", "cash": 1500, "currency": "INR"},
        ]
    }
    result = merge_competition_signals(meta, "hackathon")
    assert result["prize_inr"] == 5000
    assert result["prize_text"] == "₹5,000"


@pytest.mark.parametrize(
    "label, cash, currency",
    [
        ("Adaption AI Credits for...", 1100000, "INR"),
        ("Adaption AI Credits for...", 28500, "INR"),
        ("Free .xyz Domains for To...", 114000, "INR"),
        ("Goodies", 15000, "INR"),
        ("All eligible participants.", 100000, "USD"),
        ("Eligible Builders", 80000, "USD"),
        ("Participant Reward", 419000, "INR"),
        ("All participants", 100000, "USD"),
        ("Every participant", 100000, "USD"),
        ("Vouchers", 1000, "INR"),
        ("Coupons", 1000, "INR"),
        ("Merchandise", 1000, "INR"),
        ("Merch", 1000, "INR"),
        ("Swag", 1000, "INR"),
        ("Subscriptions", 1000, "INR"),
        ("Licenses", 1000, "INR"),
        ("Licences", 1000, "INR"),
        ("Hampers", 1000, "INR"),
        ("Gift", 1000, "INR"),
    ],
)
def test_non_money_and_participant_rewards_do_not_count(label, cash, currency):
    reward = {"rank": label.upper(), "cash": cash, "currency": currency}
    meta = {"prizes": [reward], "prize_inr": 999999, "prize_text": "stale"}
    assert prize_pool_inr(meta) is None
    result = merge_competition_signals(meta, "hackathon")
    assert "prize_inr" not in result
    assert "prize_text" not in result
    meta["prizes"].append({"rank": "Winner First Prize", "cash": 3500, "currency": "INR"})
    result = merge_competition_signals(meta, "hackathon")
    assert result["prize_inr"] == 3500
    assert result["prize_text"] == "₹3,500"


@pytest.mark.parametrize(
    "label", ["Creditworthy winners", "Domainstorm winners", "Gifted builders", "Totality winners"]
)
def test_reward_and_pool_labels_use_word_boundaries(label):
    meta = {
        "prizes": [
            {"rank": label, "cash": 100, "currency": "INR"},
            {"rank": "Second Prize", "cash": 50, "currency": "INR"},
        ]
    }
    assert prize_pool_inr(meta) == 150


@pytest.mark.parametrize(
    "prize, expected_inr, expected_text",
    [
        (" $CAD1,050 ", 66150, "CA$1,050"),
        ("$CAD1,400", 88200, "CA$1,400"),
        ("CAD500", 31500, "CAD500"),
        ("$AUD500", 28500, "A$500"),
        ("AUD500", 28500, "AUD500"),
        ("$SGD500", 33500, "S$500"),
        ("SGD500", 33500, "SGD500"),
        ("$EUR500", 50000, "$EUR500"),
        ("$GBP500", 57500, "$GBP500"),
        ("$INR500", 500, "₹500"),
        ("INR 100,000", 100000, "INR 100,000"),
        ("INR 150,000", 150000, "INR 150,000"),
        ("$CAD0", None, None),
        ("₹0", None, None),
        ("£0", None, None),
        ("Fiji", None, None),
    ],
)
def test_source_prize_text_and_currency_prefixes(prize, expected_inr, expected_text):
    meta = {"prize": prize, "prize_inr": 1, "prize_text": "stale"}
    result = merge_competition_signals(meta, "hackathon")
    assert prize_pool_inr(meta) == expected_inr
    assert result.get("prize_inr") == expected_inr
    assert result.get("prize_text") == expected_text
    if expected_inr is None:
        assert "prize_inr" not in result
        assert "prize_text" not in result


def test_mixed_currencies_display_original_amounts_with_their_grouping():
    meta = {
        "prizes": [
            {"rank": "First", "cash": 10500000, "currency": "INR"},
            {"rank": "Second", "cash": "100000", "currency": "USD"},
            {"rank": "Third", "cash": 8000, "currency": "EUR"},
            {"rank": "Fourth", "cash": 500, "currency": "GBP"},
            {"rank": "Fifth", "cash": 250000, "currency": "INR"},
        ]
    }
    result = merge_competition_signals(meta, "competition")
    assert result["prize_inr"] == 20407500
    assert result["prize_text"] == "₹1,07,50,000 + $100,000 + €8,000 + £500"
