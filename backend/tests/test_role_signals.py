"""Real listing excerpts and conservative parsing boundaries; no I/O."""

import pytest

from pipeline.role_signals import role_signals


@pytest.mark.parametrize(
    "text,country,low,high,currency,period,ote",
    [
        ("Stipend: ₹10,000/month", None, 10000, 10000, "INR", "month", False),
        ("Monthly Stipend: 40000", "IN", 40000, 40000, "INR", "month", False),
        ("Monthly Stipend: INR 32,000", None, 32000, 32000, "INR", "month", False),
        ("Monthly Stipend: 35000 INR", None, 35000, 35000, "INR", "month", False),
        ("Stipend: ₹4,000–5,000/month", None, 4000, 5000, "INR", "month", False),
        ("Stipend: INR 15000/-Month", None, 15000, 15000, "INR", "month", False),
        (
            "₹10,000 – 30,000 per month, based on what you can do",
            None,
            10000,
            30000,
            "INR",
            "month",
            False,
        ),
        (
            "Stipend: Ranges between 20,000 to 30,000 per month",
            "IN",
            20000,
            30000,
            "INR",
            "month",
            False,
        ),
        ("Compensation Bands: ₹26L – ₹30L", None, 2600000, 3000000, "INR", "year", False),
        (
            "India Annual Pay Range ₹4,900,000—₹7,000,000 INR",
            None,
            4900000,
            7000000,
            "INR",
            "year",
            False,
        ),
        (
            "Annual base salary range (excluding equity and bonus): ₹6,612,600—₹6,612,600 INR",
            None,
            6612600,
            6612600,
            "INR",
            "year",
            False,
        ),
        (
            "the estimated salary range for this role is $130,000 - $150,000",
            None,
            130000,
            150000,
            "USD",
            "year",
            False,
        ),
        ("Annual Salary: $320,000—$485,000 USD", None, 320000, 485000, "USD", "year", False),
        (
            "MongoDB's base salary range for this role in Canada is: $144,000—$200,000 CAD",
            None,
            144000,
            200000,
            "CAD",
            "year",
            False,
        ),
        ("CAN Pay Range $158,120—$198,320 CAD", None, 158120, 198320, "CAD", "year", False),
        ("Pay Range $140,054—$175,067.50 USD", None, 140054, 175067.5, "USD", "year", False),
        (
            "The base salary range for this position is $105,000.00 - $126,500.00 USD.",
            None,
            105000,
            126500,
            "USD",
            "year",
            False,
        ),
        (
            "Our cash compensation amount for this role is $147,000/yr to $190,000/yr",
            None,
            147000,
            190000,
            "USD",
            "year",
            False,
        ),
        ("Compensation is $80,000 to $100,000 annually", None, 80000, 100000, "USD", "year", False),
        ("Wage Notice $202,000—$280,000 USD", None, 202000, 280000, "USD", "year", False),
        ("Starting salary: £135,000 - £175,000 + RSUs", None, 135000, 175000, "GBP", "year", False),
        (
            "On-Target Earnings Pay Range €76.000—€105.500 EUR",
            None,
            76000,
            105500,
            "EUR",
            "year",
            True,
        ),
        (
            "The annual salary range for this full-time position is €55.800—€62.800 EUR",
            None,
            55800,
            62800,
            "EUR",
            "year",
            False,
        ),
        (
            "The OTE range for this role is: - $325,000 - $355,000",
            None,
            325000,
            355000,
            "USD",
            "year",
            True,
        ),
        ("Compensation OTE $340,000 - $380,000k", None, 340000, 380000, "USD", "year", True),
        (
            "Base pay range of $70,000 - $130,000/ CA$90,000-$160,000",
            None,
            70000,
            130000,
            "USD",
            "year",
            False,
        ),
        ("Salary: $23/hour", None, 23, 23, "USD", "hour", False),
        ("Stipend ₹15,000–5,000 per month", None, 5000, 15000, "INR", "month", False),
        (
            "Salary $130,000–150,000 USD. Salary £90,000–100,000",
            None,
            130000,
            150000,
            "USD",
            "year",
            False,
        ),
    ],
)
def test_explicit_pay(text, country, low, high, currency, period, ote):
    expected = {"min": low, "max": high, "currency": currency, "period": period, "source": "text"}
    if ote:
        expected["ote"] = True
    assert role_signals("Intern", text, "internship", country) == {"compensation": expected}


@pytest.mark.parametrize(
    "text",
    [
        "Competitive stipend",
        "Competitivestipendpackage",
        "A stipend is available for students",
        "paid internship",
    ],
)
def test_paid_without_amount_is_internship_only(text):
    assert role_signals("", text, "internship", None) == {
        "compensation": {"paid": True, "source": "text"}
    }
    assert role_signals("", text, "job", None) == {}


@pytest.mark.parametrize(
    "text",
    [
        "Monthly cell phone stipend",
        "Monthly lifestyle stipend for wellness",
        "Professional development stipend",
        "Fertility Stipend",
        "Health and wellness stipend",
        "Weekly coffee stipend",
        "A weekly lunch stipend of $75/£75",
        "One-time stipend to set up a home office",
        "A monthly stipend to help you get to and from the office",
        "annual discretionary stipend",
        "monthly lunch stipend",
        "loan offerings ranging from ₹50,000 to ₹5 Lakh",
        "(5 LAKH+ MEMBERS FROM 35+ COUNTRIES)",
        "$5M in funding",
        "Series B of $100,000,000",
        "401(k)",
        "Weekly pay with a competitive commission structure, on average, $65,000 to $70,000 in the first year",
        "Potential for a paid stipend based on performance",
        "Your initial stipend will be set to 2.5k",
        "Salary information follows. $130,000–150,000",
        "Salary\n$130,000–150,000",
        "Stipend ₹499/month",
        "Stipend ₹1,000,001/month",
        "Salary $9,999/year",
        "Salary $3,000,001/year",
        "Wage $4/hour",
        "Wage $1,001/hour",
        "Wage ₹500/hour",
    ],
)
def test_no_speculative_or_implausible_pay(text):
    assert role_signals("", text, "internship", None) == {}


@pytest.mark.parametrize(
    "text,months",
    [
        ("Duration: 3 Months", 3),
        ("Duration: 12 months", 12),
        ("6-month internship", 6),
        ("6 months internship", 6),
        ("full-time internship for 6 months", 6),
        ("Internship duration: 6 months", 6),
        ("Duration: from 1 to 6 months", 6),
        ("Duration: 7 months to a maximum 15 months", 15),
        ("from 1 to 6 months", 6),
        ("7 months to a maximum 15 months", 15),
    ],
)
def test_internship_duration(text, months):
    assert role_signals("", text, "internship", None) == {"duration_months": months}
    assert role_signals("", text, "job", None) == {}


@pytest.mark.parametrize(
    "text",
    [
        "Duration: over 18 months",
        "Duration: 25 months",
        "Duration: 0 months",
        "Tenure: 6 months",
        "Vesting duration: 12 months",
        "Leave duration: 3 months",
    ],
)
def test_duration_rejects_unrelated_or_invalid_months(text):
    assert role_signals("", text, "internship", None) == {}


@pytest.mark.parametrize(
    "title,body,expected",
    [
        ("Part-time engineer", "", True),
        ("Part time intern", "", True),
        ("Engineer", "Type: Part-time", True),
        ("Engineer", "Employment Type: Part Time", True),
        ("Engineer", "We also have part-time colleagues.", False),
    ],
)
def test_part_time_requires_title_or_label(title, body, expected):
    assert role_signals(title, body, "job", None) == ({"part_time": True} if expected else {})


@pytest.mark.parametrize(
    "text",
    [
        "PPO",
        "pre-placement offer",
        "FTE conversion",
        "full-time conversion",
        "conversion to full-time",
        "full-time role based on performance",
    ],
)
def test_job_offer_is_internship_only(text):
    assert role_signals("", text, "internship", None) == {"job_offer": True}
    assert role_signals("", text, "job", None) == {}


@pytest.mark.parametrize("text", ["ppo", "support", "PPOs", "APPO"])
def test_ppo_is_a_case_sensitive_whole_word(text):
    assert role_signals("", text, "internship", None) == {}


def test_numeric_pay_takes_precedence_over_generic_paid_title():
    signals = role_signals("Paid internship", "Stipend ₹10,000/month", "internship", "IN")
    assert signals["compensation"]["min"] == 10000


@pytest.mark.parametrize("country", [None, "IN", "US", "CA", "GB", "DE"])
def test_unlabelled_stipend_requires_an_explicit_period(country):
    assert role_signals("", "Your initial stipend will be set to 2.5k", "internship", country) == {}


@pytest.mark.parametrize(
    "benefit",
    [
        "cell phone",
        "lifestyle",
        "wellness",
        "fitness",
        "development",
        "learning",
        "fertility",
        "coffee",
        "lunch",
        "meal",
        "home office",
        "commuter",
        "travel",
        "discretionary",
        "education",
        "internet",
        "gym",
    ],
)
def test_benefit_stipend_amount_is_never_role_pay(benefit):
    assert role_signals("", f"Monthly {benefit} stipend: ₹10,000", "internship", "IN") == {}


@pytest.mark.parametrize(
    "text,country,low,high,currency,period,ote",
    [
        (
            "the reasonably expected base pay range is between $145,830 and $219,000 for the level",
            None,
            145830,
            219000,
            "USD",
            "year",
            False,
        ),
        ("Base pay range from $130,500 to $161,000", None, 130500, 161000, "USD", "year", False),
        (
            "Base compensation range for this role is CAD $164,490 - $197,389",
            None,
            164490,
            197389,
            "CAD",
            "year",
            False,
        ),
        ("Salary: 143,000-162,000 AUD", None, 143000, 162000, "AUD", "year", False),
        ("Salary: 143,000-162,000 SGD", None, 143000, 162000, "SGD", "year", False),
        (
            "CAN base pay range per year: $133,000 - $183,000",
            None,
            133000,
            183000,
            "CAD",
            "year",
            False,
        ),
        (
            "Canada base pay range per year: $133,000 - $183,000",
            None,
            133000,
            183000,
            "CAD",
            "year",
            False,
        ),
        (
            "GBP base pay range per year: £120,000 - £168,000",
            None,
            120000,
            168000,
            "GBP",
            "year",
            False,
        ),
        (
            "Stipend Structure: Fixed pay:₹ 5,000 /month Incentive pay:₹ 500 - 3,000 /month",
            None,
            5000,
            5000,
            "INR",
            "month",
            False,
        ),
        (
            "Monthly incentive-based earnings ranging from ₹5,000 to ₹15,000",
            None,
            5000,
            15000,
            "INR",
            "month",
            False,
        ),
        (
            "The expected base pay range for this position in the San Francisco area is $148,000 - $185,000",
            None,
            148000,
            185000,
            "USD",
            "year",
            False,
        ),
        ("a monthly stipend of ₹5,000 to ₹25,000.", None, 5000, 25000, "INR", "month", False),
        ("Salary: $25.00/Hr", None, 25, 25, "USD", "hour", False),
        (
            "salary range (GEOZONE 1): $27.70 - $31.99",
            None,
            27.7,
            31.99,
            "USD",
            "hour",
            False,
        ),
        ("Salary: up to INR 3.5 lakhs per year", None, 350000, 350000, "INR", "year", False),
        (
            "Compensation: ₹4,00,000–₹6,50,000 annually",
            None,
            400000,
            650000,
            "INR",
            "year",
            False,
        ),
        ("with an annual compensation of ₹8,00,000", None, 800000, 800000, "INR", "year", False),
        (
            "with a monthly salary range of ₹20,000 to ₹30,000",
            None,
            20000,
            30000,
            "INR",
            "month",
            False,
        ),
        (
            "Initially for 6 months you will get the Stipend of 15K/month",
            "IN",
            15000,
            15000,
            "INR",
            "month",
            False,
        ),
        (
            "a monthly performance-based stipend of ₹2,250–₹4,500.",
            None,
            2250,
            4500,
            "INR",
            "month",
            False,
        ),
        ("Compensation:Stipend (8000 -16,000)", "IN", 8000, 16000, "INR", "month", False),
        ("Internship compensation of €550/month", None, 550, 550, "EUR", "month", False),
        (
            "the Marketing Growth Analytics & Operations Intern is $800 USD monthly gross",
            None,
            800,
            800,
            "USD",
            "month",
            False,
        ),
        ("are paid $21/hour", None, 21, 21, "USD", "hour", False),
        ("Pay Range: $18-23/hour", None, 18, 23, "USD", "hour", False),
        (
            "Estimated annual salary of 136,000 - 187,000 USD",
            None,
            136000,
            187000,
            "USD",
            "year",
            False,
        ),
        (
            "Compensation: Approximately €16,800–€19,600 net per year",
            None,
            16800,
            19600,
            "EUR",
            "year",
            False,
        ),
        ("Total OTE $247,000 - $281,000", None, 247000, 281000, "USD", "year", True),
    ],
)
def test_production_review_pay_examples(text, country, low, high, currency, period, ote):
    expected = {
        "min": low,
        "max": high,
        "currency": currency,
        "period": period,
        "source": "text",
    }
    if ote:
        expected["ote"] = True
    assert role_signals("Intern", text, "internship", country) == {"compensation": expected}


@pytest.mark.parametrize(
    "text",
    [
        "Stipend: Unpaid initially; performance-based evaluation",
        "Stipend: Unpaid initially; may convert to a paid internship",
        "This is an unpaid internship",
    ],
)
def test_unpaid_beats_paid_language(text):
    assert role_signals("Paid internship", text, "internship", "IN") == {
        "compensation": {"unpaid": True, "source": "text"}
    }


@pytest.mark.parametrize(
    "text",
    [
        "can receive a stipend of up to ₹75,000, up to 15 AICTE academic credits",
        "stipend of ₹15,000",
        "Your initial stipend will be set to 2.5k",
    ],
)
def test_unlabelled_stipend_is_not_assumed_monthly(text):
    assert role_signals("Intern", text, "internship", "IN") == {}


def test_paid_internship_opportunity_stays_paid():
    text = "This is a paid internship opportunity"
    assert role_signals("", text, "internship", None) == {
        "compensation": {"paid": True, "source": "text"}
    }
    assert role_signals("", text, "job", None) == {}


@pytest.mark.parametrize(
    "prefix,currency",
    [("A$", "AUD"), ("S$", "SGD"), ("C$", "CAD"), ("CA$", "CAD")],
)
def test_explicit_dollar_currency_prefixes(prefix, currency):
    assert role_signals("", f"Salary: {prefix}143,000-162,000", "job", None) == {
        "compensation": {
            "min": 143000,
            "max": 162000,
            "currency": currency,
            "period": "year",
            "source": "text",
        }
    }


@pytest.mark.parametrize("currency", ["AUD", "SGD"])
@pytest.mark.parametrize(
    "amount,period",
    [
        (99, "month"),
        (20001, "month"),
        (9999, "year"),
        (3000001, "year"),
        (4, "hour"),
        (1001, "hour"),
    ],
)
def test_new_currencies_keep_non_inr_plausibility_bounds(currency, amount, period):
    assert role_signals("", f"Salary: {amount} {currency}/{period}", "job", None) == {}


@pytest.mark.parametrize(
    "text",
    [
        "143,000-162,000 AUD",
        "143,000-162,000 SGD",
        "Bonus: ₹5,000/month",
        "Commission: ₹5,000/month",
        "Stipend Structure: Incentive pay: ₹500-3,000/month",
    ],
)
def test_currency_or_supplement_alone_is_not_pay(text):
    assert role_signals("", text, "internship", "IN") == {}


def test_fixed_pay_wins_even_when_incentive_is_listed_first():
    text = "Stipend Structure: Incentive pay: ₹500-3,000/month Fixed pay: ₹5,000/month"
    assert role_signals("", text, "internship", "IN")["compensation"] == {
        "min": 5000,
        "max": 5000,
        "currency": "INR",
        "period": "month",
        "source": "text",
    }


def test_paid_unpaid_question_is_not_unpaid() -> None:
    text = "Is it a Paid/Unpaid internship? It is a paid Internship and comes with a certificate."
    assert role_signals("Intern", text, "internship", "IN")["compensation"] == {
        "paid": True,
        "source": "text",
    }


def test_unpaid_leave_is_not_an_unpaid_internship() -> None:
    text = "This internship includes unpaid leave for exams. Stipend: ₹10,000/month"
    compensation = role_signals("Intern", text, "internship", "IN")["compensation"]
    assert compensation["max"] == 10000
