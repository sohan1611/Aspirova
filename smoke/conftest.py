"""Isolated anonymous contexts, read-only networking, and failure evidence."""

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Route, expect, sync_playwright

ARTIFACTS = Path(__file__).parent / "artifacts"


@dataclass
class Diagnostics:
    page: Page | None = None
    console: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)


DIAGNOSTICS = pytest.StashKey[Diagnostics]()


def _save_failure(item: pytest.Item, failure: str) -> None:
    diagnostics = item.stash.get(DIAGNOSTICS, Diagnostics())
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", item.nodeid)[-180:]
    screenshot = ARTIFACTS / f"{name}.png"
    messages = [*diagnostics.console, f"FAILURE: {failure}"]
    page = diagnostics.page
    if page is not None and not page.is_closed():
        try:
            if page.url == "about:blank":
                # HTTP-only failures still get useful screenshots, without a visit.
                page.set_content(f"<pre>{escape(chr(10).join(messages))}</pre>")
            page.screenshot(path=str(screenshot), full_page=True, timeout=10_000)
        except Exception as error:
            messages.append(f"Screenshot capture failed: {error}")
    elif not screenshot.exists():
        messages.append("Screenshot unavailable: browser/page setup did not finish.")
    (ARTIFACTS / f"{name}-console.log").write_text(
        "\n".join(messages) + "\n", encoding="utf-8"
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        _save_failure(item, str(report.longrepr))


@pytest.fixture(scope="session")
def site_url() -> str:
    return os.environ.get("SMOKE_SITE_URL", "https://www.aspirova.org").rstrip("/")


@pytest.fixture(scope="session")
def api_url() -> str:
    return os.environ.get("SMOKE_API_URL", "https://aspirova-api.onrender.com").rstrip(
        "/"
    )


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    expect.set_options(timeout=15_000)
    with sync_playwright() as playwright:
        # SMOKE_BROWSER_CHANNEL=chrome uses an installed Chrome (handy on Windows
        # machines whose policy blocks Playwright's bundled Chromium).
        browser = playwright.chromium.launch(
            channel=os.environ.get("SMOKE_BROWSER_CHANNEL") or None
        )
        yield browser
        browser.close()


@pytest.fixture
def viewport(request: pytest.FixtureRequest) -> dict[str, int]:
    # HTTP-only checks run once; page checks explicitly parameterize this fixture.
    return getattr(request, "param", {"width": 1280, "height": 800})


@pytest.fixture
def diagnostics(request: pytest.FixtureRequest) -> Diagnostics:
    value = Diagnostics()
    request.node.stash[DIAGNOSTICS] = value
    return value


@pytest.fixture
def page(
    browser: Browser, viewport: dict[str, int], diagnostics: Diagnostics
) -> Iterator[Page]:
    # Never load a saved storage state, a persistent profile, or authentication.
    context = browser.new_context(
        viewport=viewport,
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        service_workers="block",
    )

    def read_only(route: Route) -> None:
        request = route.request
        headers = request.headers
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            diagnostics.console.append(
                f"BLOCKED write request: {request.method} {request.url}"
            )
            route.abort()
        elif (
            headers.get("next-router-prefetch") == "1"
            or "prefetch" in headers.get("purpose", "").lower()
            or "prefetch" in headers.get("sec-purpose", "").lower()
        ):
            route.abort()
        else:
            route.continue_()

    context.route("**/*", read_only)
    page = context.new_page()
    diagnostics.page = page
    page.set_default_timeout(15_000)
    page.set_default_navigation_timeout(60_000)
    page.on(
        "console",
        lambda message: diagnostics.console.append(f"{message.type}: {message.text}"),
    )

    def record_page_error(error: Exception) -> None:
        diagnostics.page_errors.append(str(error))
        diagnostics.console.append(f"PAGEERROR: {error}")

    page.on("pageerror", record_page_error)
    try:
        yield page
    finally:
        context.close()
