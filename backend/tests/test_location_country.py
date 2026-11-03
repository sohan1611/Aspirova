import pytest

from pipeline.location_country import derive_country


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Bengaluru, Karnataka", "IN"),
        ("Mumbai, Maharashtra", "IN"),
        ("Gurugram, Haryana", "IN"),
        ("Kochi, Kerala", "IN"),
        ("Thiruvananthapuram, Kerala", "IN"),
        ("New York, NY", "US"),
        ("Austin, TX", "US"),
        ("Somewhere, California", "US"),
        ("Savannah, Georgia", "US"),
        ("San Francisco, CA", "US"),
        ("London", "GB"),
        ("Dubai", "AE"),
        ("Ulm, BW, Germany", "DE"),
        ("Tbilisi, Georgia", "GE"),
        ("Toronto, Ontario", "CA"),
        ("Sydney, NSW", "AU"),
        ("Singapore", "SG"),
        ("United States", "US"),
        ("USA", "US"),
        ("U.S.", "US"),
        ("U.S.A.", "US"),
        ("America", "US"),
        ("United Kingdom", "GB"),
        ("UK", "GB"),
        ("England", "GB"),
        ("Great Britain", "GB"),
        ("United Arab Emirates", "AE"),
        ("UAE", "AE"),
        ("Bengaluru, Germany", "DE"),
        ("Remote", None),
        ("Online", None),
        ("Anywhere", None),
        ("Work from home", None),
        ("WFH", None),
        ("", None),
        ("   ", None),
        (None, None),
        ("Moon Base Alpha", None),
    ],
)
def test_derive_country(location: str | None, expected: str | None) -> None:
    assert derive_country(location) == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("SF Office", "US"),
        ("NYC", "US"),
        ("NYC-Privy", "US"),
        ("SGP", "SG"),
        ("Luxembourg", "LU"),
        ("Düsseldorf", "DE"),
        ("Mannheim", "DE"),
        ("Bonn", "DE"),
        ("Heidelberg", "DE"),
        ("Leipzig", "DE"),
        ("Aachen", "DE"),
        ("Belgrade", "RS"),
        ("Lebanon", "LB"),
        ("Macao", "MO"),
        ("Bordeaux", "FR"),
        ("Delft", "NL"),
        ("Yerevan", "AM"),
        ("Montevideo", "UY"),
        ("Kazakhstan", "KZ"),
        ("Korea", "KR"),
        ("Reykjavík", "IS"),
        ("Schlieren", "CH"),
        ("Ramat Gan", "IL"),
        ("Bratislava", "SK"),
        ("Zaragoza", "ES"),
        ("Ajmer", "IN"),
        ("Anupgarh", "IN"),
        ("Luxembourg, LUX", "LU"),
        ("Bratislava, Bratislavský kraj, SVK", "SK"),
        ("Zaragoza, Aragon, ESP", "ES"),
        ("Cividate al Piano, Lombardy, ITA", "IT"),
        ("Unknown town, LUX", "LU"),
        ("Unknown town, lux", "LU"),
        ("Luxford", None),
        ("Example LUX Office", None),
    ],
)
def test_additional_country_aliases_and_trailing_alpha3(
    location: str,
    expected: str | None,
) -> None:
    assert derive_country(location) == expected


@pytest.mark.parametrize(
    "location",
    [
        "Online",
        "Hybrid",
        "Remote",
        "Distributed",
        "In-Office",
        "N/A",
        "Anywhere",
        "Global",
        "EMEA",
        "Europe",
        "APAC",
        "Americas",
        "LOCATION",
        "Remote, AMER",
        "Content,",
        "Time,",
        "Nassau,",
        "Beverly,",
    ],
)
def test_ambiguous_and_modality_locations_remain_unknown(location: str) -> None:
    assert derive_country(location) is None
