"""Company emails render entirely from transient objects, without database access."""

from datetime import datetime, timedelta, timezone
from html import escape

import pytest

from core import models
from core.config import get_settings
from pipeline.company_alert_email import CompanyAlertGroup, render_company_alert

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Keep transient-model rendering tests independent of the global DB cleanup."""
    yield


def _company(name="Google", slug="google", **kwargs):
    return models.Company(name=name, slug=slug, **kwargs)


def _opportunity(title="Software Engineer Intern", slug="software-intern", **kwargs):
    return models.Opportunity(
        title=title,
        slug=slug,
        category=kwargs.pop("category", "internship"),
        apply_url=kwargs.pop("apply_url", "https://example.com/apply"),
        first_seen_at=kwargs.pop("first_seen_at", NOW),
        **kwargs,
    )


def _render(groups=None, **kwargs):
    return render_company_alert(
        display_name=kwargs.pop("display_name", "Priya Sharma"),
        user_skills=kwargs.pop("user_skills", None),
        groups=groups or [CompanyAlertGroup(_company(), ["software"], [_opportunity()])],
        unsub_url="https://example.com/unsubscribe?token=test",
        now=NOW,
        **kwargs,
    )


def test_escapes_crawled_content_and_omits_unsafe_links():
    company = _company('<img src=x onerror="bad()"> & Co', logo_url="javascript:bad()")
    opportunity = _opportunity(
        '<script>alert("x")</script>',
        apply_url="javascript:alert(1)",
        location="<b>Delhi</b>",
        summary="Build <script>bad()</script> & learn",
        skills=['<img src="x">'],
    )
    _, html, text = _render([CompanyAlertGroup(company, [], [opportunity])])
    for value in (company.name, opportunity.title, opportunity.location, opportunity.summary):
        assert escape(value, quote=True) in html
        assert value not in html
    assert "&lt;img src=&quot;x&quot;&gt;" in html
    assert "javascript:" not in html
    assert "javascript:" not in text
    assert "Apply on the original listing" not in html
    assert "Following for all domains" in html


def test_missing_facts_are_omitted():
    _, html, text = _render()
    for value in ("None", "unknown", "not stated", "Where:", "Pay:", "Duration:", "Closes:"):
        assert value not in html
        assert value not in text


def test_real_facts_skills_and_both_link_destinations():
    opportunity = _opportunity(
        location="Bengaluru",
        is_remote=True,
        meta={"compensation": {"unpaid": True}, "duration_months": 6, "offers_ppo": True},
        deadline=NOW + timedelta(days=14),
        deadline_confidence="explicit",
        summary="Build useful systems for students.",
        skills=["SQL", "Python", "Go", "Java", "Linux"],
    )
    subject, html, text = _render(
        [CompanyAlertGroup(_company(domain="google.com"), ["software", "data"], [opportunity])],
        user_skills=[{"name": "PYTHON", "source": "resume"}, {"name": "sql", "source": "manual"}],
    )
    assert subject == "New at Google: Software Engineer Intern"
    for value in (
        "Hi Priya,",
        "Following for Software and Data",
        "Bengaluru · Remote",
        "Unpaid",
        "6 months",
        "Job offer possible",
        "Apply by 18 Nov",
        "You have 2 of 5 skills listed",
        "Apply on the original listing",
        "https://example.com/apply",
        "https://example.com/unsubscribe?token=test",
        f"{get_settings().site_url.rstrip('/')}/opportunity/software-intern",
    ):
        assert value in html
        assert value in text
    assert html.index(">SQL</span>") < html.index(">Python</span>") < html.index(">Go</span>")
    assert "s2/favicons?domain=google.com&amp;sz=64" in html
    assert "background-color:#0b4fd6" in html
    assert "utm_" not in html
    assert "Unsubscribe</a>" in html


@pytest.mark.parametrize("confidence", ["inferred", "unknown", None])
def test_non_explicit_deadline_is_hidden(confidence):
    _, html, text = _render(
        [
            CompanyAlertGroup(
                _company(),
                [],
                [_opportunity(deadline=NOW + timedelta(days=14), deadline_confidence=confidence)],
            )
        ]
    )
    assert "18 Nov 2026" not in html + text
    assert "Closes" not in html + text


@pytest.mark.parametrize("days,timing", [(0, "today"), (1, "tomorrow")])
def test_deadline_calendar_day_wording(days, timing):
    _, html, text = _render(
        [
            CompanyAlertGroup(
                _company(),
                [],
                [_opportunity(deadline=NOW + timedelta(days=days), deadline_confidence="explicit")],
            )
        ]
    )
    assert f"Closes {timing}" in html and f"Closes {timing}" in text


@pytest.mark.parametrize(
    "name,greeting",
    [(None, "Hi there,"), ("priya@example.com", "Hi there,"), (" Priya S ", "Hi Priya,")],
)
def test_greeting(name, greeting):
    _, html, text = _render(display_name=name)
    assert greeting in html
    assert text.startswith(greeting)


def test_caps_share_cards_fairly_and_order_internships_first():
    groups = []
    for index in range(3):
        opportunities = [
            _opportunity(
                title=f"Role {index}-{n}",
                slug=f"role-{index}-{n}",
                category="internship" if n == 0 else "job",
                first_seen_at=NOW - timedelta(hours=10 - n),
            )
            for n in range(6)
        ]
        groups.append(
            CompanyAlertGroup(_company(f"Company {index}", f"company-{index}"), [], opportunities)
        )
    _, html, text = _render(groups)
    assert html.count(">View &amp; Apply</a>") == 8
    for index, shown in enumerate((3, 3, 2)):
        label = f"+{6 - shown} more new roles at Company {index}"
        assert label in html and label in text
        assert f"/companies/company-{index}" in html + text
        assert f"Role {index}-0" in html
    assert html.index("Role 0-0") < html.index("Role 0-5")
    _, html, text = _render([groups[0]])
    assert html.count(">View &amp; Apply</a>") == 4
    assert "+2 more new roles" in html + text


def test_subject_shapes_and_one_domain_title():
    one = _opportunity()
    two = _opportunity("Data Intern", "data-intern")
    google = _company()
    microsoft = _company("Microsoft", "microsoft")
    subject, html, _ = _render([CompanyAlertGroup(google, ["software"], [one])])
    assert subject == "New at Google: Software Engineer Intern"
    assert "New Software role at Google" in html
    assert _render([CompanyAlertGroup(google, [], [one, two])])[0] == "2 new roles at Google"
    groups = [CompanyAlertGroup(google, [], [one]), CompanyAlertGroup(microsoft, [], [two])]
    assert _render(groups)[0] == "2 new roles at Google and 1 more company"
    groups.append(
        CompanyAlertGroup(_company("Meta", "meta"), [], [_opportunity(category="hackathon")])
    )
    assert _render(groups)[0] == "3 new opportunities at Google and 2 more companies"


def test_subject_and_summary_are_bounded_and_whitespace_collapsed():
    opportunity = _opportunity(
        "Software  " + "Engineer " * 20, summary="Build   " + "systems " * 80
    )
    subject, html, text = _render([CompanyAlertGroup(_company(), [], [opportunity])])
    assert len(subject) <= 90
    assert subject.endswith("…")
    assert "  " not in subject
    assert "systems systems systems" in html
    assert "systems " * 40 not in html + text


def test_identical_summary_is_omitted_and_initial_tile_is_used():
    opportunity = _opportunity(summary="Software Engineer Intern")
    _, html, _ = _render([CompanyAlertGroup(_company(), [], [opportunity])])
    assert html.count("<img ") == 1  # Only the shared Aspirova header logo.
    assert ">G</td>" in html
    assert html.count("Software Engineer Intern") == 3  # Head title, hero and linked card.


@pytest.mark.parametrize(
    "location,expected",
    [
        (
            "Afghanistan, Armenia, Azerbaijan, Bahrain, India, Japan",
            "India, Afghanistan, Armenia and 3 more",
        ),
        ("Armenia; Bahrain; Japan; india", "india, Armenia, Bahrain and 1 more"),
        ("Armenia; Bahrain, Japan; Nepal", "Armenia, Bahrain, Japan and 1 more"),
        ("Bengaluru, Karnataka, India", "Bengaluru, Karnataka, India"),
        ("Bengaluru; Karnataka; India", "Bengaluru; Karnataka; India"),
    ],
)
def test_location_is_bounded_and_prioritizes_india(location, expected):
    _, html, text = _render(
        [CompanyAlertGroup(_company(), [], [_opportunity(location=location, is_remote=True)])]
    )
    assert expected + " · Remote" in html
    assert expected + " · Remote" in text
    if "more" in expected:
        assert location not in html + text


@pytest.mark.parametrize(
    "location", [None, "unknown", " None ", "not stated", "LOCATION", "N/A", "TBD"]
)
def test_unknown_location_is_omitted(location):
    _, html, text = _render([CompanyAlertGroup(_company(), [], [_opportunity(location=location)])])
    assert ">Where</td>" not in html
    assert "Where:" not in text


@pytest.mark.parametrize("host", ["unstop.com", "himalayas.app", "arbeitnow.co.uk"])
def test_apply_label_refers_to_original_listing(host):
    apply_url = f"https://{host}/listing"
    _, html, text = _render(
        [CompanyAlertGroup(_company(), [], [_opportunity(apply_url=apply_url)])]
    )
    assert f'href="{apply_url}"' in html
    assert ">Apply on the original listing</a>" in html
    assert f"Apply on the original listing: {apply_url}" in text
    assert "Apply on company site" not in html + text


@pytest.mark.parametrize(
    "category,singular,plural",
    [("internship", "role", "roles"), ("hackathon", "opportunity", "opportunities")],
)
@pytest.mark.parametrize("remaining", [1, 2])
def test_more_link_uses_the_right_number(category, singular, plural, remaining):
    opportunities = [
        _opportunity(slug=f"listing-{index}", category=category) for index in range(4 + remaining)
    ]
    subject, html, text = _render([CompanyAlertGroup(_company(), [], opportunities)])
    assert subject == f"{4 + remaining} new {plural} at Google"
    noun = singular if remaining == 1 else plural
    label = f"+{remaining} more new {noun} at Google"
    assert label in html
    assert label in text


def test_one_listed_skill_overlap_is_singular():
    _, html, text = _render(
        [CompanyAlertGroup(_company(), [], [_opportunity(skills=["Python"])])],
        user_skills=[{"name": "python", "source": "manual"}],
    )
    assert "You have 1 of 1 skill listed" in html
    assert "You have 1 of 1 skill listed" in text
    assert "1 skills" not in html + text


@pytest.mark.parametrize("company,title", [("None", "Unknown"), ("Unknown", "None")])
def test_identity_fields_preserve_names_that_look_like_placeholders(company, title):
    subject, html, text = _render(
        [CompanyAlertGroup(_company(f"  {company}  "), [], [_opportunity(f"\t{title}  ")])]
    )
    assert subject == f"New at {company}: {title}"
    assert f">{company[0]}</td>" in html
    assert f">{company}</p>" in html
    assert f">{title}</a>" in html
    assert f"{company}\nFollowing for all domains" in text
    assert f"{title} — {company}" in text
    assert "Internship" in text
    assert f"you follow {company} on Aspirova" in html + text


def test_early_career_cards_precede_newer_senior_roles_without_dropping_them():
    definitions = [
        ("Senior Customer Engineer", "job"),
        ("Engineering MANAGER", "job"),
        ("SENIOR Platform Engineer", "job"),
        ("Software Engineer - New Grad", "job"),
        ("Systems Engineer - New Grad", "job"),
        ("Software Engineer Intern", "internship"),
    ]
    opportunities = [
        _opportunity(
            title, f"career-{index}", category=category, first_seen_at=NOW - timedelta(hours=index)
        )
        for index, (title, category) in enumerate(definitions)
    ]
    subject, html, text = _render([CompanyAlertGroup(_company(), [], opportunities)])
    assert subject == "6 new roles at Google"
    expected = [definitions[index][0] for index in (5, 3, 4, 0)]
    for part in (html, text):
        assert [part.index(title) for title in expected] == sorted(
            part.index(title) for title in expected
        )
        assert definitions[1][0] not in part
        assert definitions[2][0] not in part
        assert "+2 more new roles at Google" in part
    assert html.count(">View &amp; Apply</a>") == 4
    assert len(opportunities) == 6


@pytest.mark.parametrize(
    "names,expected",
    [
        (["Cloudflare"], "Cloudflare"),
        (["Cloudflare", "Databricks"], "Cloudflare and Databricks"),
        (["Cloudflare", "Databricks", "Figma"], "Cloudflare, Databricks and Figma"),
        (
            ["Cloudflare", "Databricks", "Figma", "Google"],
            "Cloudflare, Databricks, Figma and 1 more",
        ),
        (
            ["Cloudflare", "Databricks", "Figma", "Google", "Microsoft"],
            "Cloudflare, Databricks, Figma and 2 more",
        ),
    ],
)
def test_footer_company_names_have_one_final_conjunction(names, expected):
    groups = [
        CompanyAlertGroup(
            _company(name, f"company-{index}"), [], [_opportunity(slug=f"role-{index}")]
        )
        for index, name in enumerate(names)
    ]
    _, html, text = _render(groups)
    note = f"You get this because you follow {expected} on Aspirova."
    assert note in html
    assert note in text
