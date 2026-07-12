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
