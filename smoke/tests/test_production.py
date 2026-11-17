"""Small production canaries: no login, form submissions, or outbound clicks."""

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

import pytest
from playwright.sync_api import Error, Page, expect

from calendar_coverage import (
    assert_calendar_coverage,
    source_digest,
    wait_for_deployed_coverage,
)
from conftest import Diagnostics
from provenance import card_label_problems, disclosure_problem

VIEWPORTS = [
    pytest.param({"width": 1280, "height": 800}, id="desktop"),
    pytest.param({"width": 390, "height": 844}, id="mobile"),
]
CARD_SELECTOR = 'main a[href^="/opportunity/"][aria-label]'


def test_calendar_coverage(
    page: Page, api_url: str, record_property: Callable[[str, object], None]
) -> None:
    data_dir = Path(__file__).resolve().parents[2] / "backend/data"
    source = json.loads(
        (data_dir / "hiring_calendar_2027.json").read_text(encoding="utf-8")
    )
    metadata = json.loads(
        (data_dir / "hiring_calendar_metadata.json").read_text(encoding="utf-8")
    )
    source_rows = len(source["opportunities"])
    url = f"{api_url}/calendar/coverage"

    def fetch() -> tuple[int, dict | None]:
        response = page.request.get(url, timeout=60_000)
        try:
            try:
                body = response.json()
            except ValueError:
                body = None
            return response.status, body
        finally:
            response.dispose()

    coverage = wait_for_deployed_coverage(fetch, source_digest(source, metadata))
    record_property(
        "calendar_pending_import", json.dumps(coverage.get("pending_import"))
    )
    print(f"Calendar pending import (allowed): {coverage.get('pending_import')}")
    assert_calendar_coverage(coverage, source_rows)


def visit(page: Page, site_url: str, path: str) -> None:
    url = f"{site_url}{path}"
    response = page.goto(url, wait_until="load")
    assert (
        response is not None and response.status == 200
    ), f"{url} must return 200; got {response.status if response else 'no response'}"
    # No banner exists in the current frontend. If one appears, decline only.
    decline = page.get_by_role(
        "button", name=re.compile(r"^(Reject all|Decline non-essential)$", re.I)
    )
    if decline.count() == 1 and decline.is_visible():
        decline.click()


def test_api_health(page: Page, api_url: str) -> None:
    url = f"{api_url}/health"
    attempts = []
    for attempt in range(2):
        try:
            response = page.request.get(url, timeout=60_000)
            attempts.append(f"HTTP {response.status}")
            if response.status == 200:
                return
        except Error as error:
            attempts.append(str(error))
        if attempt == 0:
            time.sleep(20)
    pytest.fail(f"GET {url} failed, including one cold-start retry: {attempts}")


@pytest.mark.parametrize("viewport", VIEWPORTS, indirect=True)
class TestPages:
    def test_home(self, page: Page, site_url: str, diagnostics: Diagnostics) -> None:
        visit(page, site_url, "/")
        search_or_cta = page.locator(
            'input[type="search"][aria-label="Search opportunities"]:visible, '
            'a[href="#feed-search"]:visible'
        )
        expect(
            search_or_cta.first,
            "Home must show the search input or primary browse CTA",
        ).to_be_visible()
        page.evaluate("() => document.fonts.ready")
        page.evaluate(
            "() => new Promise(resolve => "
            "requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        sizes = page.evaluate(
            "() => ({scroll: document.documentElement.scrollWidth, "
            "viewport: innerWidth})"
        )
        assert (
            sizes["scroll"] <= sizes["viewport"] + 1
        ), f"Home has horizontal overflow: {sizes}"
        assert (
            not diagnostics.page_errors
        ), f"Home raised uncaught page errors: {diagnostics.page_errors}"

    @pytest.mark.parametrize("path", ["/internships", "/jobs"])
    def test_opportunity_listing(self, page: Page, site_url: str, path: str) -> None:
        visit(page, site_url, path)
        cards = page.locator(CARD_SELECTOR)
        expect(
            cards.nth(4), f"{path} must render at least 5 opportunity cards"
        ).to_be_visible()
        assert cards.count() >= 5, f"{path} rendered only {cards.count()} cards"
        # TRUST-06 / DISC-08: no verification badges; "New" only with a posted date.
        problems = card_label_problems(cards.all_inner_texts())
        assert not problems, f"{path} card labels: {problems[:3]}"

    def test_first_opportunity_detail(
        self, page: Page, site_url: str, record_property: Callable[[str, object], None]
    ) -> None:
        visit(page, site_url, "/internships")
        first_card = page.locator(CARD_SELECTOR).first
        expect(
            first_card, "Need a first internship card to check its detail"
        ).to_be_visible()
        title = first_card.get_attribute("aria-label")
        href = first_card.get_attribute("href")
        assert title and title.strip(), "First opportunity card has no title"
        assert href and href.startswith(
            "/opportunity/"
        ), f"First card has an unexpected detail URL: {href!r}"
        # Navigate to this exact card, without hovering/clicking a prefetching link.
        visit(page, site_url, href)
        expect(
            page.get_by_role("heading", level=1), "Detail title must be visible"
        ).to_have_text(title)
        expect(page.get_by_role("heading", level=1)).to_be_visible()
        apply = page.get_by_role(
            "link", name=re.compile(r"^(Apply|Verify)\b", re.I)
        ).first
        expect(
            apply, "Detail must expose an Apply/source anchor for guests"
        ).to_be_visible()
        destination = apply.get_attribute("href") or ""
        parsed = urlsplit(destination)
        host = (parsed.hostname or "").lower().rstrip(".")
        assert (
            parsed.scheme in {"http", "https"} and host
        ), f"Apply href must be absolute HTTP(S), got {destination!r}"
        site_host = (urlsplit(site_url).hostname or "").lower().rstrip(".")
        assert (
            host != "aspirova.org"
            and not host.endswith(".aspirova.org")
            and host != site_host
        ), f"Apply href must leave Aspirova, got {destination!r}"
        # TRUST-06: the page says where Apply goes, and that is where it goes.
        problem = disclosure_problem(page.locator("main").inner_text(), host)
        assert problem is None, f"{href}: {problem}"
        # Never click Apply: guests are gated and clicks write analytics.
        has_json_ld = page.locator('script[type="application/ld+json"]').count() > 0
        status = (
            "present"
            if has_json_ld
            else "absent (conditionally omitted by listing metadata)"
        )
        record_property("detail_json_ld", status)
        print(f"JSON-LD for {href}: {status}")

    def test_calendar(self, page: Page, site_url: str) -> None:
        visit(page, site_url, "/calendar")
        results = page.get_by_role("region", name="Calendar results", exact=True)
        expect(results, "Calendar must render programme entries").to_be_visible()
        expect(results, "Calendar entries must finish loading").to_have_attribute(
            "aria-busy", "false"
        )
        entry = results.get_by_role("button").first
        expect(
            entry, "Calendar must contain an entry that opens its details"
        ).to_be_visible()
        entry.click()
        drawer = page.get_by_role("dialog")
        expect(
            drawer, "Selecting a calendar entry must open the detail drawer"
        ).to_be_visible()
        official = drawer.get_by_role(
            "link", name=re.compile(r"^(Official site|Apply now)", re.I)
        )
        expect(
            official, "Calendar drawer must expose its official source link"
        ).to_be_visible()
        href = official.get_attribute("href") or ""
        parsed = urlsplit(href)
        assert (
            parsed.scheme == "https" and parsed.hostname
        ), f"Calendar official source must use an absolute HTTPS URL, got {href!r}"

    def test_pricing(self, page: Page, site_url: str) -> None:
        visit(page, site_url, "/pricing")
        for name in ("Free", "Pro"):
            plan = page.locator('[data-slot="card-title"]').filter(
                has_text=re.compile(rf"^{name}$")
            )
            expect(plan, f"Pricing must render the {name} plan").to_be_visible()
        expect(
            page.locator("body"), "Pricing must not advertise the retired ₹399 price"
        ).not_to_contain_text("₹399")


def test_sitemap(page: Page, site_url: str) -> None:
    url = f"{site_url}/sitemap.xml"
    response = page.request.get(url, timeout=60_000)
    assert response.status == 200, f"GET {url} returned {response.status}, expected 200"
    content_type = response.headers.get("content-type", "")
    assert (
        "xml" in content_type.lower()
    ), f"Sitemap must be served as XML, got {content_type!r}"
    try:
        root = ElementTree.fromstring(response.body())
    except ElementTree.ParseError as error:
        pytest.fail(f"Sitemap response is not valid XML: {error}")
    assert root.tag in {
        "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset",
        "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex",
    }, f"Expected a sitemap URL set or index, got XML root {root.tag!r}"


def test_robots(page: Page, site_url: str) -> None:
    url = f"{site_url}/robots.txt"
    response = page.request.get(url, timeout=60_000)
    assert response.status == 200, f"GET {url} returned {response.status}, expected 200"
