"""Labelled title decisions and SQL-expression parity, without a database."""

import re

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import operators

from api.filters import experience_filters, is_early_career_title


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override the suite's database cleanup for this pure unit-test module."""
    yield


@pytest.fixture(scope="session")
def engine():
    raise AssertionError("Title unit tests must never request a database engine")


TITLE_CASES = [
    ("Member of Technical Staff - New Grad", True),
    ("Senior Living Intern", True),
    ("Lead Generation Intern", True),
    ("Principal Engineering Internship 2027", True),
    ("Staff Accountant - Campus Hire", True),
    ("Senior Intern", True),
    ("Intern to Senior Engineer pipeline", True),
    ("Graduate Teaching Assistant", True),
    ("Trainee Engineer", True),
    ("Senior Software Engineer", False),
    ("Staff Engineer", False),
    ("Engineering Manager", False),
    ("Principal Scientist", False),
    ("Sr. Data Analyst", False),
    ("SENIOR SOFTWARE ENGINEER - NEW GRAD", True),
    ("Senior Engineer - New-Graduate", True),
    ("Staff Engineer - Graduate Programme", True),
    ("Lead Engineer - Graduate Program", True),
    ("Graduate Engineering Manager", True),
    ("Senior Analyst - Entry Level", True),
    ("Staff Analyst - Entry-Level", True),
    ("Manager - Campus Hiring", True),
    ("Senior Engineering Internships", True),
    ("Staff Research Interns", True),
    ("Lead Engineer Trainee", True),
    ("Principal Engineering Apprentice", True),
    ("Senior Developer Co-op", True),
    ("Software Engineer", True),
    ("Junior Data Analyst", True),
    ("Internal Audit Lead", False),
    ("International Sales Manager", False),
    ("Senior InternshipCoordinator", False),
    ("Staff Engineer - New Gradient Systems", False),
    ("Senior Graduate Teaching Assistant", False),
    ("Graduate Recruitment Manager", False),
    ("Director of Engineering", False),
    ("VP of Sales", False),
    ("Chief Technology Officer", False),
    ("Senior Staff Accountant", False),
    ("", True),
]


@pytest.mark.parametrize("title,expected", TITLE_CASES)
def test_early_career_title(title: str, expected: bool) -> None:
    assert is_early_career_title(title) is expected


@pytest.mark.parametrize("title,expected", TITLE_CASES)
def test_sql_filter_uses_the_same_title_decision(title: str, expected: bool) -> None:
    expression = experience_filters("early")[0]
    assert expression.operator is operators.or_
    senior_clause, *exception_clauses = expression.clauses
    assert senior_clause.operator is operators.inv
    senior_match = senior_clause.element.element
    assert senior_match.operator.opstring == "~*"
    decisions = [not re.search(senior_match.right.value, title, re.IGNORECASE)]
    # Evaluate the actual SQL clauses and their bound regex strings with Python's
    # regex engine. Both engines support these patterns. No connection is made.
    for clause in exception_clauses:
        match = bool(re.search(clause.right.value, title, re.IGNORECASE))
        assert clause.operator.opstring == "~*"
        decisions.append(match)
    assert any(decisions) is expected
    assert any(decisions) is is_early_career_title(title)
    assert "coalesce(opportunities.title_normalized" in str(
        expression.compile(dialect=postgresql.dialect())
    )
