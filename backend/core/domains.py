"""Shared company-domain normalization and identity exclusions."""

from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse, urlsplit

JOB_BOARD_HOSTS = frozenset(
    {
        "lever.co",
        "greenhouse.io",
        "ashbyhq.com",
        "workable.com",
        "smartrecruiters.com",
        "recruitee.com",
        "keka.com",
        "myworkdayjobs.com",
        "workday.com",
        "icims.com",
        "bamboohr.com",
        "breezy.hr",
        "jobvite.com",
        "teamtailor.com",
        "personio.de",
        "personio.com",
        "unstop.com",
        "devfolio.co",
        "devpost.com",
        "hackerearth.com",
        "himalayas.app",
        "jobicy.com",
        "remoteok.com",
        "arbeitnow.com",
        "linkedin.com",
        "indeed.com",
        "glassdoor.com",
        "wellfound.com",
        "angel.co",
        "naukri.com",
        "internshala.com",
        "instahyre.com",
        "cutshort.io",
    }
)

SHARED_HOSTS = frozenset(
    {
        "google.com",
        "goo.gl",
        "forms.gle",
        "bit.ly",
        "tinyurl.com",
        "linktr.ee",
        "notion.site",
        "notion.so",
        "github.io",
        "github.com",
        "gitlab.io",
        "medium.com",
        "substack.com",
        "wordpress.com",
        "blogspot.com",
        "wixsite.com",
        "webflow.io",
        "framer.website",
        "carrd.co",
        "vercel.app",
        "netlify.app",
        "herokuapp.com",
        "typeform.com",
        "calendly.com",
        "youtube.com",
        "youtu.be",
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "t.me",
        "wa.me",
        "whatsapp.com",
        "wikipedia.org",
        "amazonaws.com",
        "cloudfront.net",
        "zoom.us",
        "microsoft.com",
        "office.com",
        "sharepoint.com",
    }
)

LEGAL_SUFFIXES = frozenset(
    {
        "ab",
        "ag",
        "as",
        "bv",
        "co",
        "company",
        "corp",
        "corporation",
        "gmbh",
        "group",
        "holdings",
        "inc",
        "incorporated",
        "kg",
        "limited",
        "llc",
        "llp",
        "ltd",
        "oy",
        "plc",
        "private",
        "pty",
        "pvt",
        "sa",
        "sas",
        "srl",
    }
)


def clean_domain(value: Any, *, owner_key: str | None = None) -> str | None:
    """Extract a host, allowing platform roots only for their matching owner."""
    if not isinstance(value, str):
        return None
    raw_domain = value.strip().lower()
    if not raw_domain:
        return None
    try:
        parsed = urlparse(raw_domain if "://" in raw_domain else f"//{raw_domain}")
        domain = (parsed.hostname or "").strip(".").removeprefix("www.")
    except ValueError:
        return None
    if "." not in domain:
        return None
    try:
        ip_address(domain)
    except ValueError:
        pass
    else:
        return None
    for host in JOB_BOARD_HOSTS | SHARED_HOSTS:
        if domain == host or domain.endswith("." + host):
            if (
                domain == host
                and owner_key is not None
                and owner_key.replace(" ", "") == host.split(".")[0]
            ):
                return domain
            return None
    return domain


def same_site(a: str, b: str) -> bool:
    """Compare hosts without a public-suffix list, allowing parent/subdomains."""
    a = a.lower().removeprefix("www.")
    b = b.lower().removeprefix("www.")
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def http_url(value: Any) -> str | None:
    """Return value when it is a well-formed absolute http(s) URL, else None.

    urlsplit, not httpx.URL: httpx 0.28 percent-encodes a malformed host such as
    "https://[broken" instead of rejecting it.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not host or "." not in host:
        return None
    if any(character in host for character in "%[] "):
        return None
    return text
