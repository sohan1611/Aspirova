import pytest

from provenance import card_label_problems, disclosure_problem


def card(*lines: str) -> str:
    return "\n".join(lines)


def test_honest_cards_pass_even_with_claim_words_in_titles() -> None:
    cards = [
        card("Partner Manager", "Acme", "Job", "via Unstop", "Posted 2d ago"),
        card("Certified Nursing Assistant", "Care Co", "Seen 3d ago"),
        card("Official Language Translator", "Gov", "New", "Posted 1d ago"),
        card("Software Engineer", "New York", "Seen 1w ago"),
    ]
    assert card_label_problems(cards) == []


BADGES = ["Verified", "verified employer", "✓ Verified", "Official listing"]


@pytest.mark.parametrize("badge", [*BADGES, "Trusted source"])
def test_verification_badges_fail(badge: str) -> None:
    problems = card_label_problems(
        [card("Data Analyst", "Acme", badge, "Posted 2d ago")]
    )
    assert len(problems) == 1 and "verification claim" in problems[0]


def test_new_needs_a_source_posting_date() -> None:
    assert card_label_problems([card("Intern", "Acme", "New", "Posted 1d ago")]) == []
    problems = card_label_problems([card("Intern", "Acme", "New", "Seen 1d ago")])
    assert len(problems) == 1 and "'New' without a source posting date" in problems[0]


NOTE = "Aspirova never handles your application."


@pytest.mark.parametrize(
    "caption,apply_host",
    [
        (f"Opens Amazon's own site (amazon.jobs). {NOTE}", "www.amazon.jobs"),
        (
            "Opens SJ Innovation's careers listing, hosted on Keka "
            f"(sjinnovation.keka.com). {NOTE}",
            "sjinnovation.keka.com",
        ),
        (
            "Opens this listing on Unstop (unstop.com). "
            f"Unstop is a job board, not Swiggy's own site. {NOTE}",
            "unstop.com",
        ),
        (
            "Opens the original listing on example.org. "
            f"We haven't confirmed this is Acme's own site. {NOTE}",
            "jobs.example.org",
        ),
        (f"Opens the original listing. {NOTE}", "anything.example"),
        (
            "Opens Acme (India)'s own site (acme.in) "
            f"so you can check whether it is still open. {NOTE}",
            "careers.acme.in",
        ),
    ],
)
def test_disclosure_matches_apply_destination(caption: str, apply_host: str) -> None:
    assert disclosure_problem(f"Title\n{caption}\nMore", apply_host) is None


def test_disclosure_host_mismatch_and_missing_disclosure_fail() -> None:
    caption = f"Opens Amazon's own site (amazon.jobs). {NOTE}"
    mismatch = disclosure_problem(caption, "evil.example")
    assert mismatch == "disclosure names amazon.jobs but Apply goes to evil.example"
    assert "no 'Opens" in disclosure_problem("Apply on Amazon", "amazon.jobs")
