"""Describe outbound application hosts without making network requests."""

import re
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

DestinationKind = Literal["company", "job_board", "event_platform", "ats", "unverified"]

DIRECT_SOURCE_SLUGS = frozenset(
    {"greenhouse", "lever", "ashby", "smartrecruiters", "amazon", "keka", "recruitee", "workable"}
)

_ARBEITNOW_HOST_RE = re.compile(r"^([a-z0-9-]+\.)*arbeitnow\.[a-z]{2,3}(\.[a-z]{2})?$")


@dataclass(frozen=True)
class ApplyDestination:
    kind: DestinationKind
    host: str | None = None
    label: str | None = None


def _host(value: str | None, *, domain: bool = False) -> str | None:
    if not value or re.search(r"[\s\\]", value):
        return None
    try:
        parsed = urlsplit(value if not domain or "://" in value else f"https://{value}")
        if parsed.scheme.lower() not in {"http", "https"}:
            return None
        host = parsed.hostname
        parsed.port  # Reject malformed ports as well as malformed hosts.
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().removeprefix("www.")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if not re.fullmatch(
        r"([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]*[a-z0-9])?",
        ascii_host,
    ):
        try:
            ip_address(host)
        except ValueError:
            return None
    return host


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def classify_destination(apply_url: str | None, company_domain: str | None) -> ApplyDestination:
    host = _host(apply_url)
    if host is None:
        return ApplyDestination("unverified")
    for domain, label in (
        ("unstop.com", "Unstop"),
        ("devpost.com", "Devpost"),
        ("devfolio.co", "Devfolio"),
        ("hackerearth.com", "HackerEarth"),
    ):
        if _matches(host, domain):
            return ApplyDestination("event_platform", host, label)
    company_host = _host(company_domain, domain=True)
    if company_host and _matches(host, company_host):
        return ApplyDestination("company", host)
    if _matches(host, "amazon.jobs"):
        return ApplyDestination("company", host)
    for domain, label in (
        ("himalayas.app", "Himalayas"),
        ("remoteok.com", "RemoteOK"),
        ("remoteok.io", "RemoteOK"),
        ("jobicy.com", "Jobicy"),
    ):
        if _matches(host, domain):
            return ApplyDestination("job_board", host, label)
    if _ARBEITNOW_HOST_RE.fullmatch(host):
        return ApplyDestination("job_board", host, "Arbeitnow")
    for domain, label in (
        ("greenhouse.io", "Greenhouse"),
        ("lever.co", "Lever"),
        ("ashbyhq.com", "Ashby"),
        ("smartrecruiters.com", "SmartRecruiters"),
        ("keka.com", "Keka"),
        ("recruitee.com", "Recruitee"),
        ("workable.com", "Workable"),
        ("myworkdayjobs.com", "Workday"),
    ):
        if _matches(host, domain):
            return ApplyDestination("ats", host, label)
    return ApplyDestination("unverified", host)
