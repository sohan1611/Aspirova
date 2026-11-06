"""Company-domain normalization and same-site comparisons."""

import pytest

from core.domains import JOB_BOARD_HOSTS, SHARED_HOSTS, clean_domain, same_site, http_url


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Example.COM", "example.com"),
        ("  https://WWW.Example.com/jobs?q=intern#apply  ", "example.com"),
        ("www.example.com/path", "example.com"),
        ("https://user:password@example.com:8443/jobs", "example.com"),
        (".example.com.", "example.com"),
        ("jobs.example.co.uk", "jobs.example.co.uk"),
        ("notgoogle.com", "notgoogle.com"),
        ("google.com.example.org", "google.com.example.org"),
        (None, None),
        (123, None),
        ({}, None),
        ("", None),
        ("  ", None),
        ("localhost", None),
        ("https://intranet/jobs", None),
        ("127.0.0.1", None),
        ("https://192.0.2.1:443/jobs", None),
        ("https://[2001:db8::1]/jobs", None),
        ("https://[::ffff:192.0.2.1]/jobs", None),
        ("https://[broken", None),
    ],
)
def test_clean_domain(value, expected) -> None:
    assert clean_domain(value) == expected


@pytest.mark.parametrize("host", sorted(JOB_BOARD_HOSTS | SHARED_HOSTS))
@pytest.mark.parametrize("prefix", ["", "www.", "tenant.jobs."])
def test_clean_domain_excludes_platform_hosts_and_subdomains(host: str, prefix: str) -> None:
    assert clean_domain(f"https://{prefix}{host}/apply") is None


@pytest.mark.parametrize(
    "value, owner_key, expected",
    [
        ("google.com", "google", "google.com"),
        ("devfolio.co", "devfolio", "devfolio.co"),
        ("hackerearth.com", "hackerearth", "hackerearth.com"),
        ("hackerearth.com", "hacker earth", "hackerearth.com"),
        ("https://WWW.Google.com/jobs", "google", "google.com"),
        ("jobs.lever.co", "lever", None),
        ("jobs.lever.co", "acme", None),
        ("google.com", None, None),
        ("google.com", "acme", None),
        ("google.com", "", None),
        ("google.com", "google labs", None),
    ],
)
def test_clean_domain_allows_only_platform_owners(value, owner_key, expected) -> None:
    assert clean_domain(value, owner_key=owner_key) == expected


@pytest.mark.parametrize("host", sorted(JOB_BOARD_HOSTS | SHARED_HOSTS))
def test_clean_domain_allows_platform_root_but_excludes_tenants_for_owner(host: str) -> None:
    owner_key = host.split(".")[0]

    assert clean_domain(host, owner_key=owner_key) == host
    assert clean_domain(f"tenant.{host}", owner_key=owner_key) is None


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("example.com", "example.com", True),
        ("WWW.EXAMPLE.COM", "example.com", True),
        ("jobs.example.com", "WWW.Example.com", True),
        ("example.com", "apply.jobs.example.com", True),
        ("notexample.com", "example.com", False),
        ("example.com.other.org", "example.com", False),
        ("jobs.example.com", "careers.example.com", False),
        ("example.org", "example.com", False),
    ],
)
def test_same_site(a: str, b: str, expected: bool) -> None:
    assert same_site(a, b) is expected
    assert same_site(b, a) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://cdn.example.com/logo.png", "https://cdn.example.com/logo.png"),
        ("  http://cdn.example.com/a.jpg ", "http://cdn.example.com/a.jpg"),
        ("https://[broken", None),
        ("https://%5Bbroken/logo.png", None),
        ("javascript:alert(1)", None),
        ("ftp://cdn.example.com/logo.png", None),
        ("https://localhost/logo.png", None),
        ("", None),
        (None, None),
    ],
)
def test_http_url_accepts_only_well_formed_http_urls(value, expected) -> None:
    assert http_url(value) == expected
