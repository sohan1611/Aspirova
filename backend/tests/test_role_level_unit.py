import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.role_level import classify_role_level, load_role_level_overrides
from scripts.role_level_review import STUDENT_QUERIES, needs_review

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "role_levels.json").read_text("utf-8"))


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """These unit tests must never open the suite's database cleanup connection."""
    yield


@pytest.fixture(scope="session")
def engine():
    raise AssertionError("Role-level unit tests must never request a database engine")


@pytest.mark.parametrize("row", FIXTURES, ids=lambda row: row["title"])
def test_classifier_preserves_exact_evidence(row):
    assert classify_role_level(row["title"], row.get("category"), row.get("meta")) == {
        "level": row["level"],
        "evidence": row["evidence"],
        "source": row.get("source", "title"),
    }


def test_override_wins_over_all_other_evidence(monkeypatch):
    from core import role_level

    override = {
        "slug": "test-role",
        "level": "unknown",
        "reason": "Employer confirmed mixed levels",
    }
    monkeypatch.setattr(role_level, "ROLE_LEVEL_OVERRIDES", {"test-role": override})
    assert classify_role_level(
        "Senior Intern", "internship", {"eligible_experienced_only": True}, "test-role"
    ) == {"level": "unknown", "evidence": override["reason"], "source": "override"}


def test_checked_in_overrides_are_valid():
    assert isinstance(load_role_level_overrides(), dict)
    assert len(FIXTURES) >= 60


@pytest.mark.parametrize(
    "rows",
    [
        {},
        [{}],
        [{"slug": "x", "level": "senior", "reason": "checked"}],
        [{"slug": "x", "level": "graduate", "reason": " "}],
        [{"slug": " ", "level": "graduate", "reason": "checked"}],
        [{"slug": "x", "level": "graduate", "reason": "checked", "extra": True}],
        [{"slug": "x", "level": "graduate", "reason": "checked"}] * 2,
    ],
)
def test_rejects_invalid_overrides(tmp_path, rows):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ValueError):
        load_role_level_overrides(path)


@pytest.mark.parametrize(
    "title,meta,expected",
    [
        ("Product Manager", {}, True),
        ("Legal Counsel", {}, True),
        ("Software Engineer", {}, False),
        ("Associate Product Manager", {}, False),
        ("Senior Intern", {"eligible_experienced_only": True}, True),
        ("Lead Generation Intern", {"eligibility": ["Experienced Professionals"]}, True),
        ("Senior Engineer", {"eligibility": ["Fresher"]}, True),
        ("Senior Engineer", {"eligibility": ["Experienced Professionals"]}, False),
        ("Senior Engineer", {"eligibility": [{"bad": "tag"}]}, False),
    ],
)
def test_review_queue(title, meta, expected):
    assert needs_review(title, "job", meta, "test-slug") is expected


def test_benchmark_queries_are_fixed():
    assert len(STUDENT_QUERIES) == 20
    assert STUDENT_QUERIES[:3] == ("software engineer", "data analyst", "product")


def test_list_and_detail_responses_include_employer_role_evidence():
    from api.schemas import OpportunityDetail, OpportunityListItem
    from core import models

    opportunity = models.Opportunity(
        slug="senior-role",
        title="Senior Software Engineer",
        title_normalized="old intern title",
        company=None,
        category="job",
        apply_url="https://example.com/job",
        deadline_confidence="unknown",
        last_seen_at=datetime.now(UTC),
        first_seen_at=datetime.now(UTC),
        is_hidden=False,
        meta={},
        status="active",
    )
    for schema in (OpportunityListItem, OpportunityDetail):
        assert schema.from_model(opportunity).model_dump()["role_level"] == {
            "level": "experienced",
            "evidence": "Senior",
            "source": "title",
        }


def test_review_cli_requires_explicit_database_url(monkeypatch, capsys):
    import sys

    from scripts.role_level_review import main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["role_level_review", "review", "--csv", "unused.csv"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "Set DATABASE_URL explicitly" in capsys.readouterr().err
