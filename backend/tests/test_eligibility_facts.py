"""Hand-written eligibility truth cases; no private audit data lives here."""

import json
from pathlib import Path

import pytest

from core.eligibility_facts import ELIGIBILITY_FACTS_VERSION, _plain, extract_eligibility_facts
from scripts.eligibility_eval import DIMENSIONS, evaluate

CASES = json.loads((Path(__file__).parent / "fixtures/eligibility_facts.json").read_text("utf-8"))


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Pure parser/evaluation tests do not need a database."""
    yield


@pytest.mark.parametrize("row", CASES, ids=[row["id"] for row in CASES])
def test_eligibility_fixture(row):
    facts = extract_eligibility_facts(
        row["title"],
        row["description_raw"],
        row["meta"],
        location=row.get("location"),
        is_remote=row.get("is_remote"),
    )
    assert facts["v"] == ELIGIBILITY_FACTS_VERSION == 3
    legacy = {
        "grad_years",
        "stages",
        "final_year_only",
        "degree_levels",
        "college_restriction",
        "citizenship",
    }
    assert {
        key: value["value"]
        for key, value in facts.items()
        if key != "v" and (row["id"].startswith("disc06-") or key in legacy)
    } == row["expected"]
    sources = {
        "title": _plain(row["title"]),
        "description": _plain(row["description_raw"]),
        "tags": "\n".join(row["meta"].get("eligibility", []))
        + "\n"
        + row["meta"].get("sponsorship", ""),
        "location": _plain(row.get("location")),
    }
    for key, fact in facts.items():
        if key == "v":
            continue
        assert 0 < len(fact["evidence"]) <= 160
        assert fact["evidence"] in sources[fact["source"]]


def test_fixture_count_and_scan_cap():
    assert len(CASES) >= 70
    assert sum(row["id"].startswith("disc06-") for row in CASES) >= 50
    assert extract_eligibility_facts("Role", "x" * 60_001 + " 2026 batch", {}) == {
        "v": ELIGIBILITY_FACTS_VERSION
    }
    assert extract_eligibility_facts(None, None, None) == {"v": ELIGIBILITY_FACTS_VERSION}


def test_evaluation_counts_errors_and_draws():
    samples = {
        "a": {"draw": "random", "title": "2026 batch"},
        "b": {"draw": "eligibility_words", "title": "PhD student"},
    }
    labels = {identifier: {key: None for key in DIMENSIONS} for identifier in samples}
    labels["a"]["grad_years"] = [2025, 2026]
    labels["b"]["stages"] = ["undergraduate"]
    scores, errors = evaluate(samples, labels)
    assert scores["random"]["grad_years"] == {"TP": 1, "FP": 0, "FN": 1}
    assert scores["eligibility_words"]["stages"] == {"TP": 0, "FP": 1, "FN": 1}
    assert scores["overall"]["grad_years"] == scores["random"]["grad_years"]
    assert [(e["id"], e["dimension"]) for e in errors] == [("a", "grad_years"), ("b", "stages")]
    with pytest.raises(ValueError, match="ids must match"):
        evaluate(samples, {})


def test_remote_unions_keep_first_exact_clause_and_ignore_unrelated_sources():
    description = "Remote within India; Remote in the Philippines"
    facts = extract_eligibility_facts(
        "Role", description, {}, location="United States", is_remote=True
    )
    assert facts["remote_regions"] == {
        "value": ["IN", "PH", "US"],
        "evidence": "Remote within India",
        "source": "description",
    }
    assert facts == extract_eligibility_facts(
        "Role", description, {}, location="United States", is_remote=True
    )
    assert "work_authorization" not in facts
    assert "citizenship" not in facts


def test_scalar_restrictions_quote_the_decisive_clause():
    facts = extract_eligibility_facts(
        "Fully remote", "Hybrid; No visa sponsorship", {"sponsorship": "Offers Sponsorship"}
    )
    assert facts["remote_mode"] == {
        "value": "hybrid",
        "evidence": "Hybrid",
        "source": "description",
    }
    assert facts["visa_sponsorship"] == {
        "value": False,
        "evidence": "No visa sponsorship",
        "source": "description",
    }
