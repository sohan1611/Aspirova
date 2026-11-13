"""Recorded discovery fixtures and in-memory HTTP transports only."""

import json
from pathlib import Path
from urllib.robotparser import RobotFileParser

import httpx
import pytest

from core.domains import JOB_BOARD_HOSTS, SHARED_HOSTS, clean_domain
from pipeline.ats_logos import (
    board_from_token,
    board_from_url,
    board_logo_url,
    extract_board_logo,
)
from pipeline.company_logos import (
    CLEARBIT_API,
    MAX_BODY_BYTES,
    MAX_ATS_BODY_BYTES,
    PARKED_MARKERS,
    USER_AGENT,
    WIKIDATA_API,
    Candidate,
    FetchResult,
    Homepage,
    HttpFetcher,
    Params,
    clearbit_candidates,
    discover_domain,
    icon_candidates,
    inspect_homepage,
    listing_candidates,
    score_candidates,
    title_matches,
    wikidata_candidates,
    wikimedia_logo_url,
)
from pipeline.normalize import company_key

FIXTURES = Path(__file__).parent / "fixtures" / "logos"
RequestKey = tuple[str, tuple[tuple[str, str], ...]]


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue() -> None:
    """Override conftest's database cleanup for this database-free module."""


def request_key(url: str, params: Params | None = None) -> RequestKey:
    return url, tuple(sorted((key, str(value)) for key, value in (params or {}).items()))


class FakeFetcher:
    def __init__(self) -> None:
        self.responses: dict[RequestKey, FetchResult | None] = {}
        self.calls: list[RequestKey] = []

    def add(
        self,
        url: str,
        content: bytes,
        *,
        params: Params | None = None,
        status: int = 200,
        final_url: str | None = None,
    ) -> None:
        self.responses[request_key(url, params)] = FetchResult(
            status, final_url or url, {}, content
        )

    def get(
        self, url: str, *, params: Params | None = None, max_bytes: int = MAX_BODY_BYTES
    ) -> FetchResult | None:
        key = request_key(url, params)
        self.calls.append(key)
        return self.responses.get(key)


def recorded_fetcher(name: str, stem: str) -> FakeFetcher:
    fetcher = FakeFetcher()
    search = (FIXTURES / f"wikidata_search_{stem}.json").read_bytes()
    ids = "|".join(entry["id"] for entry in json.loads(search)["search"][:7])
    fetcher.add(
        WIKIDATA_API,
        search,
        params={
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "type": "item",
            "limit": 7,
            "format": "json",
        },
    )
    fetcher.add(
        WIKIDATA_API,
        (FIXTURES / f"wikidata_entities_{stem}.json").read_bytes(),
        params={
            "action": "wbgetentities",
            "ids": ids,
            "props": "labels|aliases|claims",
            "languages": "en",
            "format": "json",
        },
    )
    fetcher.add(
        CLEARBIT_API,
        (FIXTURES / f"clearbit_{stem}.json").read_bytes(),
        params={"query": name},
    )
    for path in sorted(FIXTURES.glob("home_*.html")):
        host = path.name.removeprefix("home_").removesuffix(".html")
        domain = host.removeprefix("www.")
        fetcher.add(f"https://{domain}/", path.read_bytes(), final_url=f"https://{host}/")
    return fetcher


@pytest.mark.parametrize(
    ("name", "signals", "status", "score"),
    [
        ("Alan", {"wikidata"}, "not_found", 3),
        ("Alan", {"wikidata", "clearbit"}, "found", 4),
        ("Alan Labs", {"wikidata"}, "found", 3),
    ],
)
def test_name_token_count_sets_acceptance_threshold(
    name: str, signals: set[str], status: str, score: int
) -> None:
    domain = "alan.example"
    homepage = Homepage(domain, url=f"https://{domain}/", titles=(name,))
    decision = score_candidates(company_key(name), [Candidate(domain, signals)], {domain: homepage})
    assert decision.status == status
    assert decision.domain == (domain if status == "found" else None)
    assert decision.candidates[domain].score == score


@pytest.mark.parametrize(
    ("name", "signals", "fetch_homepage"),
    [
        ("Alan", {"wikidata"}, False),
        ("Alan", {"wikidata", "clearbit"}, True),
        ("Alan Labs", {"wikidata"}, True),
    ],
)
def test_homepage_pruning_uses_name_threshold(
    monkeypatch: pytest.MonkeyPatch, name: str, signals: set[str], fetch_homepage: bool
) -> None:
    domain = "alan.example"
    monkeypatch.setattr(
        "pipeline.company_logos.wikidata_candidates",
        lambda fetcher, name: [Candidate(domain, signals)],
    )
    monkeypatch.setattr("pipeline.company_logos.clearbit_candidates", lambda fetcher, name: [])
    fetcher = FakeFetcher()
    fetcher.add(f"https://{domain}/", f"<title>{name}</title>".encode())
    decision = discover_domain(fetcher, name, [], {})
    assert (request_key(f"https://{domain}/") in fetcher.calls) == fetch_homepage
    assert (request_key(f"https://{domain}/robots.txt") in fetcher.calls) == fetch_homepage
    assert decision.status == ("found" if fetch_homepage else "not_found")


def test_worldquant_exact_match_in_any_position() -> None:
    fetcher = recorded_fetcher("WorldQuant", "worldquant")
    assert [candidate.domain for candidate in clearbit_candidates(fetcher, "WorldQuant")] == [
        "worldquant.com"
    ]
    decision = discover_domain(fetcher, "WorldQuant", [], {})
    assert decision.status == "found"
    assert decision.domain == "worldquant.com"
    assert set(decision.candidates) == {"worldquant.com"}
    assert decision.candidates["worldquant.com"].score == 4
    assert decision.candidates["worldquant.com"].signals == ["clearbit", "title", "wikidata"]


@pytest.mark.parametrize(
    ("name", "domain"), [("Devfolio", "devfolio.co"), ("Google", "google.com")]
)
def test_platform_owner_keeps_wikidata_clearbit_and_title_signals(name: str, domain: str) -> None:
    fetcher = recorded_fetcher(name, "worldquant")
    key = next(key for key in fetcher.responses if ("action", "wbgetentities") in key[1])
    response = fetcher.responses[key]
    assert response is not None
    data = json.loads(response.content)
    entity = data["entities"]["Q48740825"]
    entity["labels"]["en"]["value"] = name
    entity["claims"]["P856"] = [{"mainsnak": {"datavalue": {"value": f"https://{domain}"}}}]
    fetcher.responses[key] = FetchResult(200, response.url, {}, json.dumps(data).encode())
    fetcher.add(
        CLEARBIT_API,
        json.dumps([{"name": name, "domain": domain}]).encode(),
        params={"query": name},
    )
    fetcher.add(f"https://{domain}/", f"<title>{name}</title>".encode())
    decision = discover_domain(fetcher, name, [], {})
    assert (decision.status, decision.domain) == ("found", domain)
    assert decision.candidates[domain].signals == ["clearbit", "title", "wikidata"]
    assert decision.candidates[domain].score == 4


def test_listing_platform_host_requires_its_owner_and_never_allows_tenants() -> None:
    texts = ["https://devfolio.co/events https://acme.devfolio.co/jobs"]
    assert listing_candidates(texts, owner_key=company_key("Acme")) == []
    candidates = listing_candidates(texts, owner_key=company_key("Devfolio"))
    assert [(candidate.domain, candidate.signals) for candidate in candidates] == [
        ("devfolio.co", {"listing"})
    ]


@pytest.mark.parametrize("host", sorted(JOB_BOARD_HOSTS | SHARED_HOSTS))
def test_excluded_hosts_allow_only_matching_root_owners(host: str) -> None:
    owner_key = company_key(host.split(".")[0])
    assert clean_domain(host) is None
    assert clean_domain(host, owner_key="acme") is None
    assert clean_domain(host, owner_key=owner_key) == host
    assert clean_domain(f"acme.{host}", owner_key=owner_key) is None
    assert listing_candidates([f"https://acme.{host}/jobs"], owner_key="acme") == []


def test_iit_madras_merges_research_park_without_double_counting() -> None:
    name = "Indian Institute of Technology Madras"
    fetcher = recorded_fetcher(name, "iit_madras")
    candidates = wikidata_candidates(fetcher, name)
    assert {candidate.domain for candidate in candidates} == {"iitm.ac.in", "respark.iitm.ac.in"}
    decision = discover_domain(fetcher, name, [], {})
    assert (decision.status, decision.domain) == ("found", "iitm.ac.in")
    assert set(decision.candidates) == {"iitm.ac.in", "cubeiitm.org"}
    assert decision.candidates["iitm.ac.in"].score == 3
    assert decision.candidates["iitm.ac.in"].signals == ["title", "wikidata"]
    assert decision.candidates["cubeiitm.org"].score == 1
    assert decision.p154_filename == "IIT Madras Logo (Black and White).svg"
    assert request_key("https://respark.iitm.ac.in/") not in fetcher.calls


@pytest.mark.parametrize("with_listing", [False, True])
def test_physical_intelligence_needs_listing_evidence(with_listing: bool) -> None:
    name = "Physical Intelligence"
    fetcher = recorded_fetcher(name, "physical_intelligence")
    texts = ["Read about us at physicalintelligence.company"] if with_listing else []
    decision = discover_domain(fetcher, name, texts, {})
    assert decision.candidates["physicalintelligence.com"].score == 1
    assert decision.candidates["physicalintelligence.com"].signals == ["clearbit"]
    assert request_key("https://physicalintelligence.com/") not in fetcher.calls
    assert request_key("https://physicalintelligence.com/robots.txt") not in fetcher.calls
    if with_listing:
        assert (decision.status, decision.domain) == ("found", "physicalintelligence.company")
        assert decision.candidates["physicalintelligence.company"].score == 3
    else:
        assert (decision.status, decision.domain) == ("not_found", None)


def test_tiny_company_clearbit_only_skips_homepage() -> None:
    fetcher = FakeFetcher()
    fetcher.add(
        CLEARBIT_API,
        b'[{"name": "Tiny Inc.", "domain": "tiny.example"}]',
        params={"query": "Tiny"},
    )
    fetcher.add("https://tiny.example/", b"<title>Tiny Inc.</title>")
    decision = discover_domain(fetcher, "Tiny", [], {})
    assert decision.status == "not_found"
    assert decision.candidates["tiny.example"].score == 1
    assert decision.candidates["tiny.example"].signals == ["clearbit"]
    assert all(url in {WIKIDATA_API, CLEARBIT_API} for url, _ in fetcher.calls)


@pytest.mark.parametrize("marker", PARKED_MARKERS)
@pytest.mark.parametrize("in_title", [False, True])
def test_parked_pages_score_zero(marker: str, in_title: bool) -> None:
    fetcher = FakeFetcher()
    html = (
        f"<title>Acme {marker.upper()}</title>"
        if in_title
        else f"<title>Acme</title><body>{marker.upper()}</body>"
    )
    fetcher.add("https://acme.example/", html.encode())
    homepage = inspect_homepage(fetcher, "acme.example", {})
    decision = score_candidates(
        "acme",
        [Candidate("acme.example", {"wikidata", "listing", "clearbit"})],
        {homepage.domain: homepage},
    )
    assert homepage.parked
    assert decision.status == "not_found"
    assert decision.candidates[homepage.domain].score == 0
    assert decision.candidates[homepage.domain].parked


def test_parked_markers_ignore_scripts_styles_and_text_after_first_5kb() -> None:
    fetcher = FakeFetcher()
    fetcher.add(
        "https://acme.example/",
        b"<head><title>Acme</title><script>GoDaddy</script><style>parked</style></head>"
        b"<body>" + b"x" * 5121 + b" domain for sale</body>",
    )
    assert not inspect_homepage(fetcher, "acme.example", {}).parked


def test_sedona_labs_does_not_match_sedo() -> None:
    fetcher = FakeFetcher()
    fetcher.add("https://acme.example/", b"<title>Sedona Labs</title><body>Sedona Labs</body>")
    assert not inspect_homepage(fetcher, "acme.example", {}).parked


@pytest.mark.parametrize("marker", PARKED_MARKERS)
def test_marker_word_boundaries_apply_in_title_and_visible_text(marker: str) -> None:
    fetcher = FakeFetcher()
    fetcher.add(
        "https://acme.example/",
        f"<title>pre{marker}post</title><body>pre{marker}post</body>".encode(),
    )
    assert not inspect_homepage(fetcher, "acme.example", {}).parked


@pytest.mark.parametrize("marker", ["parked", "godaddy", "coming soon"])
def test_weak_parked_markers_ignore_long_page_body(marker: str) -> None:
    fetcher = FakeFetcher()
    # The marker is inside the first 5 KB, but the whole page exceeds the short-page limit.
    body = marker + " " + "Our team builds products for customers around the world. " * 30
    fetcher.add("https://acme.example/", f"<title>Acme</title><body>{body}</body>".encode())
    assert not inspect_homepage(fetcher, "acme.example", {}).parked


@pytest.mark.parametrize("in_title", [False, True])
def test_strong_markers_and_title_markers_still_disqualify_long_pages(in_title: bool) -> None:
    fetcher = FakeFetcher()
    title = "Acme - Coming soon" if in_title else "Acme"
    body = "Our team builds products for customers around the world. " * 30
    if not in_title:
        body = "Buy this domain. " + body
    fetcher.add("https://acme.example/", f"<title>{title}</title><body>{body}</body>".encode())
    assert inspect_homepage(fetcher, "acme.example", {}).parked


def test_domain_name_for_sale_in_title_is_parked() -> None:
    fetcher = FakeFetcher()
    fetcher.add("https://acme.example/", b"<title>example.com is for sale</title>")
    assert inspect_homepage(fetcher, "acme.example", {}).parked


@pytest.mark.parametrize(("length", "parked"), [(999, True), (1000, False)])
def test_weak_marker_uses_whole_visible_text_length(length: int, parked: bool) -> None:
    fetcher = FakeFetcher()
    body = "Coming soon " + "x" * (length - 12)
    fetcher.add("https://acme.example/", f"<title>Acme</title><body>{body}</body>".encode())
    assert inspect_homepage(fetcher, "acme.example", {}).parked == parked


@pytest.mark.parametrize(
    ("key", "status", "with_titles"),
    [("acme labs", "ambiguous", False), ("acme", "not_found", False), ("acme", "ambiguous", True)],
)
def test_two_winners_are_ambiguous_and_signals_count_once(
    key: str, status: str, with_titles: bool
) -> None:
    candidates = [
        Candidate("one.example", {"wikidata"}),
        Candidate("one.example", {"wikidata"}),
        Candidate("one.example", {"clearbit"}),
        Candidate("two.example", {"listing", "clearbit"}),
    ]
    homepages = {
        domain: Homepage(domain, url=f"https://{domain}/", titles=(key,))
        for domain in ("one.example", "two.example")
        if with_titles
    }
    decision = score_candidates(key, candidates, homepages)
    assert (decision.status, decision.domain) == (status, None)
    assert [candidate.score for candidate in decision.candidates.values()] == (
        [4, 4] if with_titles else [3, 3]
    )


def test_robots_disallow_skips_homepage_and_caches_per_domain() -> None:
    fetcher = FakeFetcher()
    fetcher.add("https://acme.example/robots.txt", b"User-agent: AspirovaBot\nDisallow: /\n")
    cache: dict[str, RobotFileParser] = {}
    for _ in range(2):
        homepage = inspect_homepage(fetcher, "acme.example", cache)
        assert not homepage.allowed
        assert not homepage.titles and not homepage.icons
    assert fetcher.calls == [request_key("https://acme.example/robots.txt")]
    urls = icon_candidates("acme.example", homepage, "logo.png")
    assert any("duckduckgo.com" in url for url in urls)
    assert any("google.com" in url for url in urls)
    assert any("commons.wikimedia.org" in url for url in urls)


@pytest.mark.parametrize("robots_status", [None, 404, 500])
def test_robots_failure_allows_homepage(robots_status: int | None) -> None:
    fetcher = FakeFetcher()
    if robots_status is not None:
        fetcher.add("https://acme.example/robots.txt", b"", status=robots_status)
    fetcher.add("https://acme.example/", b"<title>Acme</title>")
    homepage = inspect_homepage(fetcher, "acme.example", {})
    assert homepage.allowed
    assert title_matches("acme", homepage)


def test_listing_candidates_filter_hosts_rank_frequency_and_limit_to_five() -> None:
    candidates = listing_candidates(
        [
            "https://boards.greenhouse.io/acme https://acme.lever.co/x "
            "https://forms.gle/join google.com https://tenant.vercel.app "
            "https://acme.github.io www.example.com example.co.in example.co.in "
            "https://www.example.com/jobs https://one.example/ two.example "
            "three.example four.example five.example person@mail.example "
            "https://127.0.0.1/jobs localhost",
        ]
    )
    assert [candidate.domain for candidate in candidates] == [
        "example.com",
        "example.co.in",
        "one.example",
        "two.example",
        "three.example",
    ]
    assert all(candidate.signals == {"listing"} for candidate in candidates)


def test_listing_domains_with_sentence_punctuation() -> None:
    candidates = listing_candidates(["Visit WWW.EXAMPLE.COM. Or example.co.in, for details."])
    assert [candidate.domain for candidate in candidates] == ["example.com", "example.co.in"]


def test_homepage_metadata_icons_hygiene_and_final_url() -> None:
    fetcher = FakeFetcher()
    fetcher.add(
        "https://acme.example/",
        b"""<head><title>Welcome</title>
        <meta property="og:site_name" content="Acme - Careers">
        <meta property="og:title" content="Acme home">
        <meta name="application-name" content="Acme app">
        <link rel="icon" sizes="16x16" href="/small.ico">
        <link rel="shortcut icon" sizes="64x64" href="../medium.png">
        <link rel="apple-touch-icon-precomposed" sizes="180x180" href="//cdn.example/large.png">
        <link rel="apple-touch-icon" sizes="180x180" href="//cdn.example/large.png">
        <link rel="icon" sizes="512x512" href="/vector.SVG?x=1">
        <link rel="icon" type="image/svg+xml" href="/vector">
        <link rel="icon" href="data:image/png;base64,AAAA">
        <link rel="icon" href="javascript:alert(1)">
        <link rel="icon" href="https://[broken">
        </head>""",
        final_url="https://www.acme.example/home/",
    )
    homepage = inspect_homepage(fetcher, "acme.example", {})
    assert homepage.url == "https://www.acme.example/home/"
    assert homepage.icons == (
        "https://www.acme.example/vector.SVG?x=1",
        "https://cdn.example/large.png",
        "https://www.acme.example/medium.png",
        "https://www.acme.example/small.ico",
        "https://www.acme.example/vector",
    )
    assert homepage.titles == ("Welcome", "Acme - Careers", "Acme home", "Acme app")
    assert title_matches("acme", homepage)
    assert icon_candidates("acme.example", homepage, "Logo with spaces.png") == [
        *homepage.icons,
        "https://acme.example/apple-touch-icon.png",
        "https://icons.duckduckgo.com/ip3/acme.example.ico",
        "https://www.google.com/s2/favicons?domain=acme.example&sz=128",
        "https://commons.wikimedia.org/wiki/Special:FilePath/Logo%20with%20spaces.png?width=256",
    ]


@pytest.mark.parametrize(
    ("title", "final_url", "matches"),
    [
        ("The ACME, Labs careers", "https://www.acme.example/", True),
        ("Acme Labs", "https://jobs.acme.example/", True),
        ("Acme Labshire", "https://acme.example/", False),
        ("Myacme Labs", "https://acme.example/", False),
        ("Acme Labs", "https://other.example/", False),
        ("Acme Labs", "https://acme.example.other.example/", False),
        ("Acme Labs", "https://acme.com/", True),
    ],
)
def test_title_token_boundaries_and_redirects(title: str, final_url: str, matches: bool) -> None:
    assert (
        title_matches("acme labs", Homepage("acme.example", final_url, titles=(title,))) == matches
    )


@pytest.mark.parametrize("final_domain,accepted", [("acme.com", True), ("other.com", False)])
def test_discovery_redirect_keeps_the_same_brand_requirement(final_domain, accepted) -> None:
    fetcher = FakeFetcher()
    fetcher.add(
        "https://acme.example/",
        b"<title>Acme Labs</title>",
        final_url=f"https://{final_domain}/",
    )
    decision = discover_domain(fetcher, "Acme Labs", ["https://acme.example/jobs"], {})
    assert (decision.domain == "acme.example") == accepted
    assert decision.candidates["acme.example"].score == (3 if accepted else 2)


def test_wikidata_alias_humans_ended_websites_and_url_hygiene() -> None:
    name = "Indian Institute of Technology Madras"
    fetcher = recorded_fetcher(name, "iit_madras")
    key = next(key for key in fetcher.responses if ("action", "wbgetentities") in key[1])
    response = fetcher.responses[key]
    assert response is not None
    data = json.loads(response.content)
    entity = data["entities"]["Q858662"]
    entity["labels"]["en"]["value"] = "Another label"
    entity["aliases"]["en"].append({"value": name + " Pvt Ltd"})
    original = entity["claims"]["P856"][0]
    for value in [
        "javascript:example.com",
        "ftp://example.com",
        "https://[broken",
        "https://github.com/x",
    ]:
        entity["claims"]["P856"].append({"mainsnak": {"datavalue": {"value": value}}})
    entity["claims"]["P856"].append(
        {"mainsnak": {"datavalue": {"value": "https://old.example"}}, "qualifiers": {"P582": [{}]}}
    )
    fetcher.responses[key] = FetchResult(200, response.url, {}, json.dumps(data).encode())
    assert {candidate.domain for candidate in wikidata_candidates(fetcher, name)} == {
        "iitm.ac.in",
        "respark.iitm.ac.in",
    }
    entity["claims"]["P31"].append({"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}})
    fetcher.responses[key] = FetchResult(200, response.url, {}, json.dumps(data).encode())
    assert [candidate.domain for candidate in wikidata_candidates(fetcher, name)] == [
        "respark.iitm.ac.in"
    ]
    assert original["mainsnak"]["datavalue"]["value"] == "http://www.iitm.ac.in"


def test_failed_sources_contribute_no_signal() -> None:
    fetcher = FakeFetcher()
    fetcher.add(CLEARBIT_API, b"broken json", params={"query": "Acme"})
    assert clearbit_candidates(fetcher, "Acme") == []
    decision = discover_domain(fetcher, "Acme", [], {})
    assert (decision.status, decision.candidates) == ("not_found", {})
    assert company_key("Acme Pvt. Ltd.") == "acme"
    assert "%2F" in wikimedia_logo_url("Logo/name.png")


def test_http_fetcher_limits_each_host_including_redirects() -> None:
    now = [0.0]
    requests: list[tuple[httpx.Request, float]] = []

    def sleep(seconds: float) -> None:
        now[0] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request, now[0]))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/finish"})
        return httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpFetcher(client, clock=lambda: now[0], sleep=sleep)
        result = fetcher.get("https://acme.example/start", params={"key": "value"})
        assert result is not None and result.url == "https://acme.example/finish"
        assert result.content == b"ok"
        fetcher.get("https://acme.example/again")
        fetcher.get("https://other.example/")
    assert [at for _, at in requests] == [0.0, 1.0, 2.0, 2.0]
    assert requests[0][0].url.params["key"] == "value"
    assert all(request.headers["user-agent"] == USER_AGENT for request, _ in requests)
    assert all(request.extensions["timeout"]["read"] == 10.0 for request, _ in requests)


@pytest.mark.parametrize("redirects", [5, 6])
def test_http_fetcher_follows_at_most_five_redirects(redirects: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        index = int(request.url.path.strip("/"))
        if index < redirects:
            return httpx.Response(302, headers={"Location": f"/{index + 1}"})
        return httpx.Response(200, content=b"done")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = HttpFetcher(client, sleep=lambda _: None).get("https://acme.example/0")
    assert (result is not None) == (redirects == 5)
    assert len(calls) == 6


@pytest.mark.parametrize("declared_length", [False, True])
def test_http_fetcher_caps_bodies(declared_length: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = b"x" * (MAX_BODY_BYTES + 1)
        response = httpx.Response(200, content=content)
        if not declared_length:
            del response.headers["content-length"]
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert HttpFetcher(client).get("https://acme.example/") is None


def test_http_fetcher_returns_none_on_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert HttpFetcher(client).get("https://acme.example/") is None


@pytest.mark.parametrize(
    ("vendor", "board", "expected"),
    [
        (
            "greenhouse",
            "https://job-boards.greenhouse.io/fiveringsllc",
            "https://s3-recruiting.cdn.greenhouse.io/external_greenhouse_job_boards/logos/000/001/original/logo.jpg",
        ),
        (
            "lever",
            "https://jobs.lever.co/example",
            "https://lever-client-logos.s3.us-west-2.amazonaws.com/example.png",
        ),
        ("ashby", "https://jobs.ashbyhq.com/saronic", "https://cdn.example/saronic-square.png"),
        (
            "workday",
            "https://example.wd5.myworkdayjobs.com/External",
            "https://example.wd5.myworkdayjobs.com/External/assets/logo",
        ),
    ],
)
def test_board_logo_extraction_from_saved_html(vendor: str, board: str, expected: str) -> None:
    assert extract_board_logo(board, (FIXTURES / f"board_{vendor}.html").read_bytes()) == expected


@pytest.mark.parametrize(
    ("url", "board"),
    [
        ("https://boards.greenhouse.io/acme/jobs/123", "https://job-boards.greenhouse.io/acme"),
        ("https://job-boards.greenhouse.io/acme/jobs/123", "https://job-boards.greenhouse.io/acme"),
        ("https://jobs.lever.co/acme/123/apply", "https://jobs.lever.co/acme"),
        ("https://jobs.ashbyhq.com/acme/123", "https://jobs.ashbyhq.com/acme"),
        (
            "https://acme.wd1.myworkdayjobs.com/en-US/Jobs/job/123",
            "https://acme.wd1.myworkdayjobs.com/Jobs",
        ),
        (
            "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/Jobs/job/123",
            "https://acme.wd1.myworkdayjobs.com/Jobs",
        ),
        ("https://jobs.lever.co.evil.example/acme/123", None),
        ("https://jobs.lever.co/", None),
    ],
)
def test_board_url_identity(url: str, board: str | None) -> None:
    assert board_from_url(url) == board


@pytest.mark.parametrize("vendor", ["greenhouse", "lever", "ashby", "workday"])
def test_crawler_board_tokens_round_trip(vendor: str) -> None:
    token = "acme|wd5|External" if vendor == "workday" else "acme"
    board = board_from_token(vendor, token)
    assert board and board_from_url(board) == board
    assert board_from_token(vendor, "../invalid") is None


def test_board_robots_policy_is_cached_and_respects_path() -> None:
    fetcher = FakeFetcher()
    fetcher.add("https://jobs.lever.co/robots.txt", b"User-agent: *\nDisallow: /blocked\n")
    cache = {}
    assert board_logo_url(fetcher, "https://jobs.lever.co/blocked", cache) is None
    assert board_logo_url(fetcher, "https://jobs.lever.co/blocked", cache) is None
    assert fetcher.calls == [request_key("https://jobs.lever.co/robots.txt")]


def test_board_redirect_to_another_employer_is_rejected() -> None:
    fetcher = FakeFetcher()
    board = "https://jobs.lever.co/acme"
    fetcher.add(
        board, (FIXTURES / "board_lever.html").read_bytes(), final_url="https://jobs.lever.co/other"
    )
    assert board_logo_url(fetcher, board, {}) is None


def test_lever_vendor_logo_is_never_an_employer_logo() -> None:
    footer = b'<img alt="Lever logo" src="https://lever-client-logos.s3.amazonaws.com/lever.png">'
    assert extract_board_logo("https://jobs.lever.co/acme", footer) is None


def test_workday_checks_robots_for_the_logo_endpoint() -> None:
    fetcher = FakeFetcher()
    fetcher.add(
        "https://acme.wd1.myworkdayjobs.com/robots.txt", b"User-agent: *\nDisallow: /Jobs/assets/\n"
    )
    assert board_logo_url(fetcher, "https://acme.wd1.myworkdayjobs.com/Jobs", {}) is None


@pytest.mark.parametrize("declared_length", [False, True])
def test_http_fetcher_larger_limit_is_per_request(declared_length: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, content=b"x" * (MAX_BODY_BYTES + 1))
        if not declared_length:
            del response.headers["content-length"]
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpFetcher(client, sleep=lambda _: None)
        assert fetcher.get("https://cdn.example/logo") is None
        assert fetcher.get("https://cdn.example/logo", max_bytes=MAX_ATS_BODY_BYTES) is not None
        assert fetcher.get("https://cdn.example/logo") is None
