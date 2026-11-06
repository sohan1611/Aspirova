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
        "zohorecruit.com",
        "zohorecruit.in",
        "zoho.com",
        "freshteam.com",
        "darwinbox.in",
        "darwinbox.com",
        "successfactors.com",
        "successfactors.eu",
        "taleo.net",
        "oraclecloud.com",
        "ultipro.com",
        "paylocity.com",
        "adp.com",
        "jazzhr.com",
        "applytojob.com",
        "pinpointhq.com",
        "rippling.com",
        "dover.com",
        "gem.com",
        "homerun.co",
        "join.com",
        "hirehive.com",
        "trakstar.com",
        "workatastartup.com",
        "ycombinator.com",
        "welcometothejungle.com",
        "otta.com",
        "weworkremotely.com",
        "remote.co",
        "flexjobs.com",
        "builtin.com",
        "dice.com",
        "monster.com",
        "careerbuilder.com",
        "ziprecruiter.com",
        "simplyhired.com",
        "foundit.in",
        "shine.com",
        "apna.co",
        "hirist.tech",
        "hirist.com",
        "iimjobs.com",
        "joinsuperset.com",
        "dare2compete.com",
        "hackerrank.com",
        "mettl.com",
        "eventbrite.com",
        "lu.ma",
        "airtable.com",
        "jotform.com",
        "tally.so",
        "hirequotient.com",
        "keka.co",
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
        "lnkd.in",
        "t.co",
        "rebrand.ly",
        "shorturl.at",
        "cutt.ly",
        "is.gd",
        "ow.ly",
        "buff.ly",
        "sites.google.com",
        "drive.google.com",
        "dropbox.com",
        "box.com",
        "canva.site",
        "my.canva.site",
        "wix.com",
        "squarespace.com",
        "godaddysites.com",
        "mystrikingly.com",
        "site123.me",
        "weebly.com",
        "jimdosite.com",
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
    excluded_hosts = JOB_BOARD_HOSTS | SHARED_HOSTS
    if (
        domain in excluded_hosts
        and owner_key is not None
        and owner_key.replace(" ", "") == domain.split(".")[0]
    ):
        return domain
    if any(domain == host or domain.endswith("." + host) for host in excluded_hosts):
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
