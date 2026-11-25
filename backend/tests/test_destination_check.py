import httpx
import pytest

from pipeline.destination_check import inspect_destination, observation_liveness


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    yield


def inspect(respond, url="https://careers.example.com/job", **kwargs):
    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        return inspect_destination(url, client, resolve=lambda *_: True, **kwargs)


@pytest.mark.parametrize(
    "code,status,liveness",
    [
        (200, "alive", "alive"),
        (404, "gone", "closed"),
        (410, "gone", "closed"),
        (401, "sign_in_required", "inconclusive"),
        (403, "unknown", "inconclusive"),
        (429, "unknown", "inconclusive"),
        (500, "unknown", "inconclusive"),
        (503, "unknown", "inconclusive"),
    ],
)
def test_status_handling(code, status, liveness):
    result = inspect(lambda _: httpx.Response(code))
    assert result["status"] == status and observation_liveness(result) == liveness
    if code in {403, 429}:
        assert result["warnings"] == [f"blocked_{code}"]


@pytest.mark.parametrize(
    "url", ["https://himalayas.app/companies/acme/jobs/intern", "https://careers.example.com/job"]
)
def test_bot_protection_403_is_unknown_without_auth_evidence(url):
    body = "<title>Access denied</title><p>Request blocked by bot protection.</p><nav>Sign in</nav>"
    result = inspect(lambda _: httpx.Response(403, text=body), url)
    assert result["status"] == "unknown" and result["warnings"] == ["blocked_403"]
    assert observation_liveness(result) == "inconclusive"
    isolated_copy = inspect(
        lambda _: httpx.Response(403, text="Please sign in to view this posting"), url
    )
    assert isolated_copy["status"] == "unknown" and isolated_copy["warnings"] == ["blocked_403"]


@pytest.mark.parametrize("code", [302, 403])
def test_redirect_to_login_host_is_auth_evidence(code):
    result = inspect(
        lambda _: httpx.Response(code, headers={"location": "https://login.example.com/"})
    )
    assert result["status"] == "sign_in_required" and result["warnings"] == ["login_wall"]
    assert result["terminal_host"] == "login.example.com"
    assert observation_liveness(result) == "inconclusive"


@pytest.mark.parametrize(
    "url,body",
    [
        ("https://example.com/login", ""),
        ("https://auth.example.com/", ""),
        ("https://example.com/job", "<form>Sign in<input type='password'></form>"),
    ],
)
def test_403_requires_a_login_terminal_url_or_form(url, body):
    result = inspect(lambda _: httpx.Response(403, text=body), url)
    assert result["status"] == "sign_in_required" and result["warnings"] == ["login_wall"]
    assert observation_liveness(result) == "inconclusive"


def test_same_site_chain_upgrade_and_ats_host_hop():
    def respond(request):
        if request.url.scheme == "http":
            return httpx.Response(301, headers={"location": "https://careers.example.com/job"})
        if request.url.host == "careers.example.com":
            return httpx.Response(302, headers={"location": "https://apply.example.com/job"})
        return httpx.Response(200)

    result = inspect(respond, "http://careers.example.com/job")
    assert result["status"] == "alive" and len(result["hops"]) == 3
    assert result["terminal_domain"] == "example.com"
    result = inspect(
        lambda r: (
            httpx.Response(
                301, headers={"location": "https://job-boards.greenhouse.io/acme/jobs/1"}
            )
            if r.url.host == "boards.greenhouse.io"
            else httpx.Response(200)
        ),
        "https://boards.greenhouse.io/acme/jobs/1",
    )
    assert result["status"] == "alive"


@pytest.mark.parametrize(
    "location,warning",
    [
        ("https://evil.com/job", "redirect_unrelated"),
        ("http://careers.example.com/job", "redirect_downgrade"),
        ("http://127.0.0.1/admin", "invalid_redirect"),
        ("javascript:alert(1)", "invalid_redirect"),
    ],
)
def test_untrusted_redirects_are_recorded_without_following(location, warning):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(301, headers={"location": location})

    result = inspect(respond)
    assert len(calls) == 1 and warning in result["warnings"]
    assert observation_liveness(result) == "inconclusive"


def test_other_tenant_on_same_ats_domain_is_unrelated():
    result = inspect(
        lambda _: httpx.Response(302, headers={"location": "https://jobs.lever.co/other/1"}),
        "https://jobs.lever.co/acme/1",
    )
    assert result["warnings"] == ["redirect_unrelated"]


def test_unknown_board_and_workday_cxs_cannot_trust_another_tenant():
    for original, target in [
        (
            "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/1",
            "https://other.wd5.myworkdayjobs.com/Careers/job/1",
        ),
        ("https://jobs.lever.co/", "https://jobs.lever.co/other/1"),
    ]:
        result = inspect(lambda _: httpx.Response(302, headers={"location": target}), original)
        assert result["warnings"] == ["redirect_unrelated"]


def test_company_tied_ats_hop_is_permitted():
    def respond(request):
        if request.url.host == "careers.example.com":
            return httpx.Response(302, headers={"location": "https://jobs.lever.co/acme/1"})
        return httpx.Response(200)

    assert inspect(respond, allowed_board=("lever", "acme"))["status"] == "alive"


@pytest.mark.parametrize("cluster,expected", [("wd5", "alive"), ("wd1", "unknown")])
def test_workday_redirects_require_the_same_normalized_board(cluster, expected):
    def respond(request):
        if request.url.host.endswith(".myworkdayjobs.com"):
            return httpx.Response(
                302,
                headers={
                    "location": f"https://{cluster}.myworkdaysite.com/recruiting/hp/externalcareersite/job/1"
                },
            )
        return httpx.Response(200)

    result = inspect(respond, "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/1")
    assert result["status"] == expected
    assert ("redirect_unrelated" in result["warnings"]) is (expected == "unknown")


@pytest.mark.parametrize("location", ["/login?next=/job", "https://accounts.other.com/signin"])
def test_redirect_to_login_is_auth_not_closed(location):
    result = inspect(lambda _: httpx.Response(302, headers={"location": location}))
    assert result["status"] == "sign_in_required"
    assert observation_liveness(result) == "inconclusive"


def test_html_login_parked_timeout_and_redirect_budget():
    for body, status in [
        ("<form>Sign in<input type='password'></form>", "sign_in_required"),
        ("This domain is for sale", "unknown"),
        ("<nav>Sign in</nav><article>Software Engineer</article>", "alive"),
    ]:
        assert inspect(lambda _: httpx.Response(200, text=body))["status"] == status

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    assert inspect(timeout)["status"] == "unknown"
    assert inspect(lambda _: httpx.Response(302, headers={"location": "/job"}))["warnings"] == [
        "redirect_loop"
    ]
    result = inspect(
        lambda r: httpx.Response(301, headers={"location": str(r.url) + "x"}), max_hops=2
    )
    assert len(result["hops"]) == 3 and result["warnings"] == ["redirect_limit"]


def test_passwordless_login_wall_is_not_alive_or_closed():
    result = inspect(
        lambda _: httpx.Response(
            200, text="<form><input type='email'><button>Sign in</button></form>"
        )
    )
    assert result["status"] == "sign_in_required"


def test_explicit_http_errors_win_over_page_wording():
    assert inspect(lambda _: httpx.Response(404), "https://example.com/login")["status"] == "gone"
    assert (
        inspect(lambda _: httpx.Response(503, text="Please sign in to view"))["status"] == "unknown"
    )


def test_invalid_url_and_private_dns_are_never_fetched():
    def respond(_):
        raise AssertionError("must not fetch")

    assert inspect(respond, "http://169.254.169.254")["status"] == "invalid"
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = inspect_destination("https://example.com", client, resolve=lambda *_: False)
    assert result["status"] == "unknown"
