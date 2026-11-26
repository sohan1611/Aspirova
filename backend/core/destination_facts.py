"""TRUST-01: deterministic destination evidence. No I/O, DNS or clock reads.

The PSL is bundled with the pinned dependency; never download it at runtime.
Company names, source names and similar-looking ATS slugs are not ownership proof.
"""

import hashlib
import json
import re
from functools import lru_cache
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

DESTINATION_FACTS_VERSION = 2
DESTINATION_TYPES = (
    "employer_ats",
    "employer_site",
    "aggregator",
    "government",
    "academic",
    "competition_platform",
    "unknown",
)
AGGREGATORS = {
    "himalayas.app": "Himalayas",
    "jobicy.com": "Jobicy",
    "remoteok.com": "RemoteOK",
    "remoteok.io": "RemoteOK",
    "arbeitnow.com": "Arbeitnow",
    "remotive.com": "Remotive",
    "remotive.io": "Remotive",
    "github.com": "GitHub lists",
    "simplify.jobs": "SimplifyJobs",
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "wellfound.com": "Wellfound",
    "internshala.com": "Internshala",
}
REPOST_SOURCES = {
    "himalayas": "Himalayas",
    "jobicy": "Jobicy",
    "remoteok": "RemoteOK",
    "arbeitnow": "Arbeitnow",
    "remotive": "Remotive",
    "unstop": "Unstop",
    "github_lists": "GitHub lists (SimplifyJobs)",
}
PLATFORMS = {
    "unstop.com": "Unstop",
    "devpost.com": "Devpost",
    "devfolio.co": "Devfolio",
    "hackerearth.com": "HackerEarth",
    "kaggle.com": "Kaggle",
    "hackerrank.com": "HackerRank",
}
ATS = {
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "ashbyhq.com": "ashby",
    "smartrecruiters.com": "smartrecruiters",
    "myworkdayjobs.com": "workday",
    "myworkdaysite.com": "workday",
    "keka.com": "keka",
    "recruitee.com": "recruitee",
    "workable.com": "workable",
    "icims.com": "icims",
    "taleo.net": "taleo",
    "successfactors.com": "successfactors",
    "oraclecloud.com": "oraclecloud",
    "bamboohr.com": "bamboohr",
    "personio.de": "personio",
    "personio.com": "personio",
}


def matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def url_key(url: str | None) -> str:
    return hashlib.sha256((url or "").strip().encode("utf-8")).hexdigest()


def destination_input_key(
    url: str | None,
    *,
    source: str | None = None,
    company_id: int | None = None,
    company_domain: str | None = None,
    ats_type: str | None = None,
    ats_board_id: str | None = None,
    email_apply: bool = False,
) -> str:
    """Fingerprint all classification evidence, including the company-board binding."""
    inputs = (url_key(url), source, company_id, company_domain, ats_type, ats_board_id, email_apply)
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=True).encode("ascii")).hexdigest()


def destination_facts_need_refresh(facts: dict | None, url: str, **context) -> bool:
    if not isinstance(facts, dict):
        return True
    version = facts.get("v")
    if type(version) is int and version > DESTINATION_FACTS_VERSION:
        return False
    return (
        type(version) is not int
        or version != DESTINATION_FACTS_VERSION
        or facts.get("input_key") != destination_input_key(url, **context)
    )


def public_host(value: str | None) -> str | None:
    """Validate a web URI, including literal IPs and browser IP shorthand."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or parsed.username is not None:
            return None
        host = parsed.hostname
        if not host or "%" in host or parsed.port == 0:
            return None
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
        # Decode A-labels too: malformed xn-- labels are not valid IDNs.
        host.encode("ascii").decode("idna")
        if len(host) > 253:
            return None
        try:
            address = ip_address(host)
        except ValueError:
            if (
                "." not in host
                or host.rsplit(".", 1)[-1].isdigit()
                or re.fullmatch(r"(?:0x[0-9a-f]+|[0-9.]+)", host)
                or any(
                    matches(host, name) for name in ("localhost", "local", "internal", "home.arpa")
                )
                or any(
                    not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
                    for p in host.split(".")
                )
            ):
                return None
        else:
            if not address.is_global or address.is_multicast:
                return None
        return host.removeprefix("www.")
    except (ValueError, UnicodeError):
        return None


@lru_cache(maxsize=2)
def _suffixes(only_icann: bool = False):
    from publicsuffixlist import PublicSuffixList

    return PublicSuffixList(only_icann=only_icann)


def registrable_domain(host: str | None) -> str | None:
    if not host:
        return None
    try:
        ip_address(host)
    except ValueError:
        return _suffixes().privatesuffix(host)
    return None


def ats_board(url: str) -> tuple[str, str] | None:
    """Extract only recognized board shapes, matching stored company board IDs."""
    host = public_host(url)
    if not host:
        return None
    parts = urlsplit(url.strip())
    path = [unquote(p) for p in parts.path.split("/") if p]
    if re.fullmatch(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io", host):
        token = (
            parse_qs(parts.query).get("for", [""])[0]
            if path[:2] == ["embed", "job_app"]
            else (path[0] if path else "")
        )
        kind = "greenhouse"
    elif host in {
        "jobs.lever.co",
        "jobs.eu.lever.co",
        "jobs.ashbyhq.com",
        "apply.workable.com",
        "jobs.smartrecruiters.com",
    }:
        kind = {
            "jobs.lever.co": "lever",
            "jobs.eu.lever.co": "lever",
            "jobs.ashbyhq.com": "ashby",
            "apply.workable.com": "workable",
            "jobs.smartrecruiters.com": "smartrecruiters",
        }[host]
        token = path[0] if path else ""
    elif re.fullmatch(r"[a-z0-9-]+\.(?:recruitee|keka|bamboohr)\.com", host):
        token, kind = host.split(".")[:2]
    elif match := re.fullmatch(r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", host):
        kind, token = "personio", match[1]
    elif match := re.fullmatch(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com", host):
        if len(path) > 1 and path[1] != "job" and _workday_locale(path[0]):
            path = path[1:]
        if not path or not re.fullmatch(r"[a-zA-Z0-9_-]+", path[0]) or path[0] in {"wday", "job"}:
            return None
        return "workday", f"{match[1]}|{match[2]}|{path[0]}".casefold()
    elif match := re.fullmatch(r"(wd\d+)\.myworkdaysite\.com", host):
        if len(path) > 1 and path[1] == "recruiting" and _workday_locale(path[0]):
            path = path[1:]
        if (
            len(path) < 3
            or path[0] != "recruiting"
            or not all(re.fullmatch(r"[a-zA-Z0-9_-]+", part) for part in path[1:3])
        ):
            return None
        return "workday", f"{path[1]}|{match[1]}|{path[2]}".casefold()
    else:
        return None
    return (kind, token) if re.fullmatch(r"[a-zA-Z0-9_-]+", token) else None


def _workday_locale(value: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z]{2}(?:[-_][a-zA-Z]{2,4}(?:[-_][a-zA-Z]{2})?)?", value))


def board_matches_company(
    board: tuple[str, str] | None,
    ats_type: str | None,
    ats_board_id: str | None,
) -> bool:
    """Match explicit board evidence; only DNS slugs and Workday IDs fold case."""
    if not board or not ats_type or not ats_board_id:
        return False
    kind, token = board
    if kind != ats_type.strip().casefold():
        return False
    expected = ats_board_id.strip()
    if kind in {"recruitee", "keka", "bamboohr", "personio", "workday"}:
        return token.casefold() == expected.casefold()
    return token == expected


def classify_destination_facts(
    url: str | None,
    company_domain: str | None = None,
    *,
    source: str | None = None,
    company_id: int | None = None,
    ats_type: str | None = None,
    ats_board_id: str | None = None,
    email_apply: bool = False,
    computed_at: str | None = None,
    observation: dict | None = None,
) -> dict[str, Any]:
    host = public_host(url)
    email = bool(
        email_apply
        and isinstance(url, str)
        and re.fullmatch(r"mailto:[^\s?@]+@[^\s?@]+\.[^\s?@]+", url)
    )
    facts: dict[str, Any] = {
        "v": DESTINATION_FACTS_VERSION,
        "computed_at": computed_at,
        "checked_at": None,
        "url_key": url_key(url),
        "input_key": destination_input_key(
            url,
            source=source,
            company_id=company_id,
            company_domain=company_domain,
            ats_type=ats_type,
            ats_board_id=ats_board_id,
            email_apply=email_apply,
        ),
        "valid": host is not None or email,
        "host": host,
        "domain": registrable_domain(host),
        "type": "unknown",
        "employer_verified": False,
        "aggregator_warning": False,
        "via": REPOST_SOURCES.get(source or ""),
        "status": "unchecked",
        "warnings": [],
    }
    if host:
        aggregator = next((label for d, label in AGGREGATORS.items() if matches(host, d)), None)
        # Match the actual registrable ICANN domain, not an Arbeitnow-named
        # tenant of a shared service such as arbeitnow.github.io.
        icann_domain = _suffixes(only_icann=True).privatesuffix(host, accept_unknown=False)
        if icann_domain and icann_domain.split(".", 1)[0] == "arbeitnow":
            aggregator = "Arbeitnow"
        platform = next((label for d, label in PLATFORMS.items() if matches(host, d)), None)
        if matches(host, "unstop.com"):
            path = [unquote(p).casefold() for p in urlsplit(url.strip()).path.split("/") if p]
            if path and path[0] in {"jobs", "internships"}:
                aggregator, platform = "Unstop", None
            elif source == "unstop":
                facts["via"] = None
        board = ats_board(url or "")
        company_host = public_host(
            company_domain if "://" in (company_domain or "") else f"https://{company_domain}"
        )
        from core.domains import clean_domain

        own = bool(
            company_host
            and registrable_domain(company_host)
            and clean_domain(company_host)
            and matches(host, company_host)
        )
        if aggregator:
            facts.update(type="aggregator", via=aggregator)
        elif platform:
            facts.update(type="competition_platform", platform=platform)
        elif any(matches(host, d) for d in ATS):
            facts.update(
                type="employer_ats",
                employer_verified=board_matches_company(board, ats_type, ats_board_id),
            )
        elif any(matches(host, d) for d in ("gov", "gov.in", "nic.in", "gov.uk", "gov.au")):
            facts.update(type="government", employer_verified=own)
        elif any(matches(host, d) for d in ("edu", "edu.in", "ac.in", "ac.uk", "edu.au")):
            facts.update(type="academic", employer_verified=own)
        elif own:
            facts.update(type="employer_site", employer_verified=True)
        elif matches(host, "amazon.jobs"):
            # The existing Amazon adapter's careers host is known. Without a
            # matching company domain, this still does not verify the employer.
            facts.update(type="employer_site")
    facts["aggregator_warning"] = bool(facts["via"])
    # Observations are tied to the exact link: never reuse checks after a URL change.
    if isinstance(observation, dict) and observation.get("url_key") == facts["url_key"]:
        facts["observation"] = observation
        facts["checked_at"] = observation.get("checked_at")
        facts["status"] = observation.get("status", "unknown")
        facts["warnings"] = list(observation.get("warnings", []))
        facts["terminal_host"] = observation.get("terminal_host")
        facts["terminal_domain"] = observation.get("terminal_domain")
        # A bot block/timeout does not disprove an exact company-domain or board
        # binding. Redirect/parked/login warnings still withhold the origin claim.
        if (
            any(warning not in {"blocked_403", "blocked_429"} for warning in facts["warnings"])
            or facts["status"] == "invalid"
        ):
            facts["employer_verified"] = False
    return facts


def retain_alive_verification(facts: dict, previous: dict | None = None) -> dict:
    """Unknown later checks cannot erase positive evidence for the same URL."""
    previous = previous if isinstance(previous, dict) else {}
    times = []
    for item in (facts, previous if previous.get("url_key") == facts.get("url_key") else {}):
        observation = item.get("observation") or {}
        if item.get("last_alive_at"):
            times.append(item["last_alive_at"])
        if item.get("status") == "alive" and 200 <= (observation.get("http_status") or 0) < 300:
            if item.get("checked_at"):
                times.append(item["checked_at"])
    if times:
        # All values originate from our UTC destination checker.
        facts["last_alive_at"] = max(times)
    return facts


def refresh_destination_facts(
    url: str,
    previous: dict | None,
    *,
    computed_at: str,
    source: str | None = None,
    company_id: int | None = None,
    company_domain: str | None = None,
    ats_type: str | None = None,
    ats_board_id: str | None = None,
) -> dict:
    previous = previous if isinstance(previous, dict) else {}
    context = dict(
        source=source,
        company_id=company_id,
        company_domain=company_domain,
        ats_type=ats_type,
        ats_board_id=ats_board_id,
    )
    if not destination_facts_need_refresh(previous, url, **context):
        return previous
    return retain_alive_verification(
        classify_destination_facts(
            url,
            company_domain,
            source=source,
            company_id=company_id,
            ats_type=ats_type,
            ats_board_id=ats_board_id,
            computed_at=computed_at,
            observation=previous.get("observation"),
        ),
        previous,
    )
