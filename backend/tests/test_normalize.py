"""Category boundaries and the shared Python/PostgreSQL new-grad pattern."""

import re

import pytest
from sqlalchemy import text

from crawlers.student_relevance import classify_student_role, is_student_relevant_role
from pipeline.normalize import NEW_GRAD_TITLE_PATTERN, classify_category


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Software Engineer, New Grad", "job"),
        ("Security Engineer, New Grad", "job"),
        ("Member of Technical Staff (New Grad)", "job"),
        ("New Graduate Software Engineer", "job"),
        ("Software Engineer I (New Grad)", "job"),
        ("Campus Recruiter - Dental Hygiene", "job"),
        ("Campus Hiring Program 2027", "job"),
        ("Internal Audit Lead", "job"),
        ("International Strategic Finance", "job"),
        ("Software Engineer, Intern", "internship"),
        ("New Graduate Internship", "internship"),
        ("Intern / New Grad Engineer", "internship"),
        ("Graduate Trainee", "internship"),
        ("Apprenticeship - UX", "internship"),
        ("Co-op Engineer", "internship"),
        ("Coop Engineer", "internship"),
        ("Campus Ambassador", "internship"),
        ("Campus Intern", "internship"),
        ("Campus Internship", "internship"),
        ("Campus Programme", "internship"),
        ("Campus Program", "internship"),
        ("Graduate Student Researcher", "internship"),
        ("Research Interns", "internship"),
        ("Summer Internships", "internship"),
        ("Apprentice - UX", "internship"),
    ],
)
def test_classify_category(title: str, expected: str) -> None:
    assert classify_category(title) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("2027 US AI Engineering – New College Graduate", "job"),
        ("Graduate Data Analyst", "job"),
        ("Graduate Trainee Developer", "internship"),
        ("Campus Hiring Program 2027", "job"),
        ("Graduate Student Researcher", "internship"),
    ],
)
def test_student_role_category_preserves_admission(title: str, expected: str) -> None:
    assert classify_student_role(title) == expected
    assert is_student_relevant_role(title) is True


@pytest.mark.parametrize(
    "title,level",
    [
        ("Graduate Data Analyst", "Internship"),
        ("New Grad Engineer", ["Graduate Student"]),
        ("New Graduate Developer", "Trainee"),
    ],
)
def test_student_role_keeps_structured_internship_levels(title: str, level: object) -> None:
    assert classify_student_role(title, level) == "internship"


NEW_GRAD_FIXTURES = [
    ("Software Engineer, New Grad", True),
    ("Security Engineer, New Grads", True),
    ("Member of Technical Staff (New Grad)", True),
    ("New Graduate Software Engineer", True),
    ("New Graduates – Engineering", True),
    ("Software Engineer I (New Grad)", True),
    ("New College Grad Engineer", True),
    ("2027 US AI Engineering – New College Graduate", True),
    ("New College Graduates", True),
    ("Recent Grad Analyst", True),
    ("Recent Graduate Analyst", True),
    ("Recent Graduates", True),
    ("University Grad Analyst", True),
    ("University Graduate Analyst", True),
    ("University Graduates", True),
    ("Campus Hire Engineer", True),
    ("Campus Hiring Program 2027", True),
    ("NEW--  COLLEGE- GRADUATE", True),
    ("Recent---Graduate", True),
    ("New Graduate Internship", True),
    ("Intern / New Grad Engineer", True),
    ("Renew Graduate Engineer", False),
    ("New Graduation Coordinator", False),
    ("Campus Recruiter - Dental Hygiene", False),
    ("Graduate Data Analyst", True),
    ("Graduate Student Researcher", False),
    ("Internal Audit Lead", False),
    ("International Strategic Finance", False),
    ("Graduate Software Engineer", True),
    ("Graduate Fire Engineer 2027 Start - Glasgow", True),
    ("Software Engineer, 2027 Graduate Australia", True),
    ("AI Research Engineer, New PhD Graduate", True),
    ("Graduate Quantitative Researcher (2027 Start)", True),
    ("Software Engineer, 2027 Graduates", True),
    ("AI Research Engineer, PhD Graduates", True),
    ("Engineering Graduate Program", True),
    ("Engineering Graduate Programs", True),
    ("Engineering Graduate Programme", True),
    ("Engineering Graduate Programmes", True),
    ("Engineering Graduate Scheme", True),
    ("Engineering Graduate Schemes", True),
    ("Graduate Recruiter", False),
    ("Graduate Admissions Officer", False),
    ("Partnerships Coordinator - Graduate Loans", False),
    ("Graduate Medical Education Coordinator", False),
    ("Graduate Research Assistant", False),
    ("Graduate  Recruiter", False),
    ("Graduate--Admissions Officer", False),
    ("Graduate Loan Adviser", False),
    ("Graduate School Coordinator", False),
    ("Graduate Teaching Assistant", False),
    ("Partnerships Coordinator - Graduate Software Engineer", False),
]


@pytest.mark.parametrize("title,expected", NEW_GRAD_FIXTURES)
def test_new_grad_title_pattern_python(title: str, expected: bool) -> None:
    assert bool(re.search(NEW_GRAD_TITLE_PATTERN, title, re.IGNORECASE)) is expected


def test_new_grad_title_pattern_postgres_matches_python(engine) -> None:
    with engine.connect() as connection:
        for title, expected in NEW_GRAD_FIXTURES:
            actual = connection.scalar(
                text("SELECT CAST(:title AS text) ~* :pattern"),
                {"title": title, "pattern": NEW_GRAD_TITLE_PATTERN},
            )
            assert actual is expected, title
            assert actual == bool(re.search(NEW_GRAD_TITLE_PATTERN, title, re.IGNORECASE))
