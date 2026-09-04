import pytest

from core.summarise import summarise_description


def test_about_us_opener_is_skipped_for_role_paragraph() -> None:
    role = (
        "We are looking for a Software Engineering Intern to join the lakehouse platform team. "
        "You will build reliable product surfaces that help students and engineers understand "
        "large datasets."
    )
    description = """
About Us
At Databricks, we are passionate about helping data teams solve hard problems.

Job Description
{role}

Responsibilities
- Build backend services
- Write tests
""".format(role=role)

    assert summarise_description(description, title="Software Engineering Intern") == role


def test_only_bullet_list_returns_none() -> None:
    description = """
- Build APIs for a student-facing product.
- Work with designers and write tests.
- Share weekly updates with the team.
"""

    assert summarise_description(description, title="Backend Engineering Intern") is None


def test_html_description_is_stripped_and_summarised() -> None:
    role = (
        "As a Product Design Intern, you will map student workflows and turn messy research "
        "into clear product surfaces. You will partner with engineering to ship polished "
        "improvements."
    )
    description = """
<section>
  <h2>Job Description</h2>
  <p>{role}</p>
  <p>Equal Opportunity Employer.</p>
</section>
""".format(role=role)

    assert summarise_description(description, title="Product Design Intern") == role


def test_shorter_than_floor_returns_none() -> None:
    assert summarise_description("You will help.", title="Intern") is None


def test_none_and_empty_input_return_none() -> None:
    assert summarise_description(None, title="Intern") is None
    assert summarise_description("", title="Intern") is None
    assert summarise_description(" \n \t ", title="Intern") is None


def test_title_repeat_block_is_skipped() -> None:
    role = (
        "This role turns messy marketplace data into clear dashboards for the growth team. "
        "You will build recurring reports and explain what changed to operators."
    )
    description = """
Data Analyst Intern

{role}
""".format(role=role)

    assert summarise_description(description, title="Data Analyst Intern") == role


def test_compensation_first_sentence_is_not_selected() -> None:
    bad = (
        "Intuit provides a competitive compensation package with a strong pay for "
        "performance rewards approach."
    )

    summary = summarise_description(bad, title="Senior Software Engineer")

    assert summary is None
    assert summary != bad


def test_company_culture_fallback_returns_none() -> None:
    bad = (
        "The same principles built into our products are reflected in how our team works: "
        "we embrace AI as a core productivity multiplier, with all team members expected "
        "to use it every day."
    )
    description = """
{bad}

Our values are visible in every meeting and planning ritual across the company.
""".format(bad=bad)

    summary = summarise_description(
        description,
        title="Director of Recruiting, Engineering & IT, Bangalore India",
    )

    assert summary is None
    assert summary != bad


def test_leading_role_section_label_is_stripped() -> None:
    expected = (
        "Lead the collections target and control collection flow for specified area. "
        "Handle large team of collection officers, their productivity and performance."
    )
    description = f"About the role: {expected}"

    summary = summarise_description(description, title="Area Collections Manager")

    assert summary == expected
    assert summary != f"About the role: {expected}"


@pytest.mark.parametrize(
    ("title", "description"),
    [
        (
            "Enterprise Account Executive - Sweden",
            "ClickHouse is on a mission to grow a vibrant global user community and "
            "accelerate our journey as a cloud first company.",
        ),
        (
            "Engineer II",
            "There has never been a better time to be at AECOM. With accelerating "
            "infrastructure investment worldwide, our services are in great demand.",
        ),
        (
            "Field Technical Program Manager",
            "At Databricks, we aim to inspire our customers to make informed decisions "
            "through an intuitive platform.",
        ),
        (
            "Senior Solutions Engineer",
            "We're an in-office company, driven by a shared commitment to excellence "
            "and velocity.",
        ),
        (
            "Senior Software Engineer, Agent Platform",
            "We're an in-office company, driven by a shared commitment to excellence "
            "and velocity.",
        ),
        (
            "Strategic Account Executive - Turkey",
            "The confidence gap exists. The above list is intended to show the kinds "
            "of experience and qualities we're looking for.",
        ),
    ],
)
def test_company_prose_without_first_sentence_role_signal_returns_none(
    title: str,
    description: str,
) -> None:
    assert summarise_description(description, title=title) is None


def test_title_token_keeps_account_manager_role_sentence() -> None:
    expected = (
        "We're hiring a results-driven account manager to own and accelerate renewals "
        "across strategic accounts."
    )

    assert (
        summarise_description(expected, title="Account Manager, Renewals & Expansion") == expected
    )


def test_first_sentence_role_marker_keeps_software_engineer_sentence() -> None:
    expected = (
        "As a software engineer with a backend focus, you will work with your team to "
        "build reliable APIs for student workflows."
    )

    assert summarise_description(expected, title="Software Engineer") == expected


def test_title_token_keeps_lyft_business_strategy_manager_sentence() -> None:
    expected = (
        "Lyft is looking for a Business Strategy Manager to accelerate the growth of "
        "our newest markets."
    )

    assert summarise_description(expected, title="Lyft Business Strategy Manager") == expected
