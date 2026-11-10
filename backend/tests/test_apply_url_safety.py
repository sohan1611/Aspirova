"""SEC-03: an Apply link that is not an absolute http(s) URL never reaches the
site. Pure model tests, no database."""

import pytest

from core.adapters import NormalizedListing


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override the suite's database cleanup for this pure unit-test module."""
    yield


@pytest.fixture(scope="session")
def engine():
    raise AssertionError("Apply URL safety tests must never request a database engine")


def _listing(apply_url: str, source_url: str = "https://boards.example.com/jobs/1"):
    return NormalizedListing(
        source_slug="greenhouse",
        external_id="1",
        source_url=source_url,
        title="Software Engineering Intern",
        company_name="Example",
        description_raw="",
        apply_url=apply_url,
    )


@pytest.mark.parametrize(
    "apply_url",
    [
        "https://example.com/apply/1",
        "http://example.com/apply?id=1&utm_source=x",
        "  https://example.com/padded  ",
    ],
)
def test_web_apply_links_are_kept_as_given(apply_url: str) -> None:
    assert _listing(apply_url).apply_url == apply_url


@pytest.mark.parametrize(
    "apply_url",
    [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        " javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "/jobs/123",
        "jobs.example.com/apply",
        "https://",
        "https://[broken",
        "",
    ],
)
def test_unsafe_apply_links_fall_back_to_the_source_page(apply_url: str) -> None:
    assert _listing(apply_url).apply_url == "https://boards.example.com/jobs/1"


def test_unsafe_apply_link_is_left_alone_when_the_source_page_is_not_a_web_link() -> None:
    # Nothing better to offer: the frontend's own guard then hides the link.
    assert _listing("javascript:alert(1)", source_url="manual").apply_url == "javascript:alert(1)"
