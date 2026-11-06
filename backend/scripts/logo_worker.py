"""Find, validate and cache company logos after a crawl.

Override README
Keys in data/company_logo_overrides.json are company slugs. Each value has
one form. {"domain": "example.com"} trusts that domain, {"logo_url":
"https://example.com/logo.png"} validates and stores that image, and
{"block": true} clears the logo. All three record a manual decision.

Run from backend with ``uv run python -m scripts.logo_worker``. Offline
review uses --from-api-json PATH --report DIR and never opens a database.
"""

import argparse
import base64
import csv
import html
import json
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.robotparser import RobotFileParser

import httpx

from core.config import Settings, get_settings
from core.domains import brand_label, clean_domain, http_url, same_site
from core.logo_store import (
    NormalizedLogo,
    best_logo,
    logo_storage_configured,
    s3_client,
    upload_logo,
)
from pipeline.company_logos import (
    Fetcher,
    FetchResult,
    Homepage,
    HttpFetcher,
    Params,
    discover_domain,
    icon_candidates,
    inspect_homepage,
    wikimedia_logo_url,
)
from pipeline.normalize import company_key

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import Subquery

    from core.models import Company

DEFAULT_OVERRIDES = Path(__file__).resolve().parents[1] / "data/company_logo_overrides.json"
STORAGE_FIELDS = (
    "logo_s3_endpoint_url",
    "logo_s3_access_key_id",
    "logo_s3_secret_access_key",
    "logo_s3_bucket",
    "logo_public_base_url",
)
CacheLookup = Callable[[str], tuple[str, dict] | None]


@dataclass
class Outcome:
    status: str = "not_found"
    source: str | None = None
    domain: str | None = None
    evidence: dict = field(default_factory=dict)
    logo: NormalizedLogo | None = None
    cached_url: str | None = None
    searched: bool = False
    error: bool = False

    @property
    def found(self) -> bool:
        return self.logo is not None or self.cached_url is not None


def guard_group(domain: str | None, name: str) -> str:
    """One brand is one group: sibling domains and same-brand names never trip the guard.

    amazon.com, aws.amazon.com and amazon.in share a favicon legitimately, and so do
    "IIT Bombay" and "IIT Bombay Techfest" when both use the institute crest. A
    platform default (Wix, WordPress, a source's placeholder) still spans three
    unrelated brands.
    """
    if domain:
        return f"brand/{brand_label(domain)}"
    tokens = company_key(name).split()
    return f"name/{tokens[0]}" if tokens else f"name/{name}"


class GenericGuard:
    """Count independent brand groups per image hash, retaining rejected hashes this run."""

    def __init__(self) -> None:
        self.groups: dict[str, set[str]] = defaultdict(set)

    def add(self, sha256: str | None, domain: str | None, name: str) -> bool:
        if not sha256:
            return False
        self.groups[sha256].add(guard_group(domain, name))
        return len(self.groups[sha256]) >= 3

    @property
    def rejected(self) -> set[str]:
        return {sha for sha, groups in self.groups.items() if len(groups) >= 3}


class LogoFetches:
    """Retain request provenance when an image service redirects its response."""

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self.origins: dict[str, str] = {}

    def get(self, url: str, *, params: Params | None = None) -> FetchResult | None:
        result = self.fetcher.get(url, params=params)
        if result is not None:
            self.origins.setdefault(result.url, url)
        return result


def load_overrides(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Overrides must be an object keyed by company slug")
    for slug, entry in data.items():
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError(f"Invalid override for {slug}")
        if entry.get("block") is True:
            continue
        if isinstance(entry.get("domain"), str) and entry["domain"].strip():
            continue
        if http_url(entry.get("logo_url")):
            continue
        raise ValueError(f"Invalid override for {slug}")
    return data


def image_outcome(logo: NormalizedLogo, source: str, domain: str | None) -> Outcome:
    return Outcome(
        "found",
        source,
        domain,
        {
            "domain": domain,
            "image_url": logo.url,
            "width": logo.width,
            "height": logo.height,
            "sha256": logo.sha256,
            "reason": "validated image",
        },
        logo=logo,
    )


def domain_logo(
    fetcher: Fetcher,
    name: str,
    domain: str,
    robots: dict[str, RobotFileParser],
    cache_lookup: CacheLookup,
    *,
    homepage: Homepage | None = None,
    p154_filename: str | None = None,
) -> Outcome:
    domain = clean_domain(domain, owner_key=company_key(name))
    result = Outcome(domain=domain, evidence={"domain": domain, "candidates": {}})
    if domain is None:
        result.evidence["reason"] = "invalid or excluded domain"
        return result
    # A sibling row already holds a validated, stored logo for this domain:
    # reuse it before spending any request on the site.
    cached = cache_lookup(domain)
    if cached:
        url, evidence = cached
        return Outcome(
            "found",
            "domain_cache",
            domain,
            {**evidence, "domain": domain, "reason": "domain cache", "candidates": {}},
            cached_url=url,
        )
    homepage = homepage or inspect_homepage(fetcher, domain, robots)
    if homepage.parked:
        result.evidence["reason"] = "parked"
        return result
    # A trusted input still must not acquire an unrelated redirect target's icon.
    final_domain = clean_domain(http_url(homepage.url), owner_key=company_key(name))
    if homepage.url and (not final_domain or not same_site(domain, final_domain)):
        result.evidence["reason"] = "homepage redirected off domain"
        return result
    p154_url = wikimedia_logo_url(p154_filename) if p154_filename else None
    requests = LogoFetches(fetcher)
    logo = best_logo(requests, icon_candidates(domain, homepage, p154_filename), p154_url=p154_url)
    if logo is None:
        result.evidence["reason"] = "no valid icon"
        return result
    source = (
        "wikidata_logo"
        if p154_url and requests.origins.get(logo.url) == p154_url
        else "domain_icon"
    )
    return image_outcome(logo, source, domain)


def resolve_logo(
    fetcher: Fetcher,
    name: str,
    domain: str | None,
    hint: str | None,
    override: dict | None,
    listing_texts: Callable[[], list[str]],
    robots: dict[str, RobotFileParser],
    cache_lookup: CacheLookup,
    accept: Callable[[Outcome], None] | None = None,
) -> Outcome:
    attempts = []
    rejected_images = []

    def acceptable(result: Outcome) -> bool:
        if result.found and accept:
            accept(result)
            if result.status == "rejected_generic":
                rejected_images.append(dict(result.evidence))
        return result.found

    if override:
        if override.get("block"):
            return Outcome("manual", evidence={"reason": "blocked by override", "domain": domain})
        if "logo_url" in override:
            logo = best_logo(fetcher, [override["logo_url"]])
            if logo:
                result = image_outcome(logo, "override", domain)
                if acceptable(result):
                    return result
            attempts.append({"step": "override", "reason": "no valid override image"})
        else:
            result = domain_logo(fetcher, name, override["domain"], robots, cache_lookup)
            if acceptable(result):
                result.source = "override"
                result.evidence["accepted_domain"] = True
                return result
            attempts.append({"step": "override", **result.evidence})
    if hint:
        logo = best_logo(fetcher, [hint])
        if logo:
            result = image_outcome(logo, "source_payload", domain)
            if acceptable(result):
                result.evidence["attempts"] = attempts
                return result
        attempts.append({"step": "source_payload", "reason": "no valid hint image"})
    if domain:
        result = domain_logo(fetcher, name, domain, robots, cache_lookup)
    else:
        decision = discover_domain(fetcher, name, listing_texts(), robots)
        candidates = {host: asdict(score) for host, score in decision.candidates.items()}
        if decision.domain:
            result = domain_logo(
                fetcher,
                name,
                decision.domain,
                robots,
                cache_lookup,
                homepage=decision.homepage,
                p154_filename=decision.p154_filename,
            )
            result.evidence["accepted_domain"] = True
        else:
            reason = "no confident domain"
            if decision.status == "ambiguous":
                reason = "multiple qualifying domains"
            elif candidates and all(score["parked"] for score in candidates.values()):
                reason = "parked"
            result = Outcome(decision.status, evidence={"domain": None, "reason": reason})
        result.evidence["candidates"] = candidates
        result.searched = True
    acceptable(result)
    if not result.found and rejected_images:
        result.status = "rejected_generic"
        result.evidence["reason"] = "same image on at least 3 independent groups"
    if rejected_images:
        result.evidence["rejected_images"] = rejected_images
    result.evidence["attempts"] = attempts
    return result


def guard_outcome(guard: GenericGuard, result: Outcome, name: str) -> None:
    if result.found and guard.add(result.evidence.get("sha256"), result.domain, name):
        result.status = "rejected_generic"
        result.source = None
        result.logo = None
        result.cached_url = None
        result.evidence["reason"] = "same image on at least 3 independent groups"


def active_filters() -> "tuple[ColumnElement[bool], ...]":
    from api.filters import (
        exclude_experienced_only_opportunities,
        exclude_school_only_opportunities,
        exclude_stale_opportunities,
    )
    from core.models import Opportunity

    return (
        Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_school_only_opportunities(),
    )


def active_counts() -> "Subquery":
    from sqlalchemy import func, select

    from core.models import Opportunity

    return (
        select(Opportunity.company_id, func.count().label("active_count"))
        .where(*active_filters())
        .group_by(Opportunity.company_id)
        .subquery()
    )


def override_needed(company: "Company", override: dict | None) -> bool:
    if override is None:
        return False
    return (
        company.logo_status != "manual"
        or (company.logo_evidence or {}).get("override") != override
        or (override.get("block") is True and company.logo_url is not None)
    )


def retry_filter(recheck_days: int) -> "ColumnElement[bool]":
    from sqlalchemy import and_, or_

    from core.models import Company

    return and_(
        Company.logo_url.is_(None),
        Company.logo_status.is_distinct_from("manual"),
        or_(
            Company.logo_status.is_(None),
            and_(
                Company.logo_status.in_(("not_found", "ambiguous", "rejected_generic")),
                Company.logo_checked_at < datetime.now(UTC) - timedelta(days=recheck_days),
            ),
        ),
    )


def select_companies(
    session: "Session", args: argparse.Namespace, overrides: dict
) -> list[tuple[int, int]]:
    from sqlalchemy import func, select

    from core.models import Company

    counts = active_counts()
    query = select(Company, counts.c.active_count).join(counts, counts.c.company_id == Company.id)
    rows = session.execute(
        query.where(retry_filter(args.recheck_days))
        .order_by(counts.c.active_count.desc(), Company.id)
        .limit(args.limit)
    ).all()
    selected = {company.id: (company.id, count) for company, count in rows}
    if overrides:
        rows = session.execute(
            select(Company, func.coalesce(counts.c.active_count, 0))
            .outerjoin(counts, counts.c.company_id == Company.id)
            .where(Company.slug.in_(overrides))
        ).all()
        for company, count in rows:
            if override_needed(company, overrides[company.slug]):
                selected[company.id] = (company.id, count)
    return sorted(selected.values(), key=lambda row: (-row[1], row[0]))


def recent_listing_texts(session: "Session", company_id: int) -> list[str]:
    from sqlalchemy import select

    from core.models import Opportunity

    rows = session.execute(
        select(Opportunity.apply_url, Opportunity.description_raw)
        .where(Opportunity.company_id == company_id, *active_filters())
        .order_by(Opportunity.first_seen_at.desc(), Opportunity.id.desc())
        .limit(5)
    ).all()
    return [f"{url or ''}\n{description or ''}" for url, description in rows]


def domain_owner(session: "Session", company_id: int, domain: str) -> "Company | None":
    from sqlalchemy import select

    from core.models import Company

    return session.scalar(select(Company).where(Company.domain == domain, Company.id != company_id))


def claim_domain(
    session: "Session", company: "Company", result: Outcome, override: dict | None
) -> None:
    from sqlalchemy.exc import IntegrityError

    if not result.domain or not result.evidence.get("accepted_domain"):
        return
    if company.domain is not None and not (override and "domain" in override):
        return
    if domain_owner(session, company.id, result.domain) is not None:
        return
    try:
        # The crawler may claim this domain after our lookup. Keep the logo
        # decision if its unique-domain write wins that race.
        with session.begin_nested():
            company.domain = result.domain
            session.flush()
    except IntegrityError:
        session.refresh(company)


def generic_post_pass(session: "Session", rejected: set[str] | None = None) -> set[int]:
    from sqlalchemy import select

    from core.models import Company

    rows = session.scalars(
        select(Company).where(Company.logo_evidence["sha256"].as_string().is_not(None))
    ).all()
    guard = GenericGuard()
    for company in rows:
        if company.logo_status == "found" and company.logo_url:
            evidence = company.logo_evidence or {}
            guard.add(evidence.get("sha256"), evidence.get("domain"), company.name)
    bad_hashes = guard.rejected | (rejected or set())
    changed = set()
    for company in rows:
        evidence = company.logo_evidence or {}
        if company.logo_status == "manual" or evidence.get("sha256") not in bad_hashes:
            continue
        if company.logo_url is not None:
            changed.add(company.id)
        company.logo_url = None
        company.logo_status = "rejected_generic"
        company.logo_source = None
        company.logo_checked_at = datetime.now(UTC)
        company.logo_evidence = {
            **evidence,
            "reason": "same image on at least 3 independent groups",
        }
    session.flush()
    return changed


def print_summary(outcomes: list[Outcome], started: float) -> None:
    counts = Counter(result.status for result in outcomes)
    sources = Counter(result.source for result in outcomes if result.found)
    print(
        f"cache_hit={sources['domain_cache']} searched={sum(r.searched for r in outcomes)} "
        f"found={dict(sources)} not_found={counts['not_found']} "
        f"ambiguous={counts['ambiguous']} rejected_generic={counts['rejected_generic']} "
        f"errors={sum(r.error for r in outcomes)} elapsed={time.monotonic() - started:.1f}s"
    )


def print_missing(session: "Session") -> None:
    from sqlalchemy import select

    from core.models import Company

    counts = active_counts()
    rows = session.execute(
        select(Company, counts.c.active_count)
        .join(counts, counts.c.company_id == Company.id)
        .where(Company.logo_url.is_(None))
        .order_by(counts.c.active_count.desc(), Company.id)
        .limit(25)
    ).all()
    print("Top companies still missing logos")
    for company, count in rows:
        reason = " ".join(str((company.logo_evidence or {}).get("reason", "unchecked")).split())
        print(f"{count:5} {company.name} [{company.logo_status}] {reason}")


def apply_outcome(
    session: "Session",
    company: "Company",
    result: Outcome,
    override: dict | None,
    uploader: Callable[[str, NormalizedLogo], str],
) -> None:
    claim_domain(session, company, result, override)
    company.logo_url = uploader(company.slug, result.logo) if result.logo else result.cached_url
    company.logo_status = "manual" if override else result.status
    company.logo_source = result.source
    company.logo_checked_at = datetime.now(UTC)
    evidence = {"domain": result.domain, "candidates": {}, **result.evidence}
    if override:
        evidence["override"] = override
    company.logo_evidence = evidence


def run_db(
    session: "Session",
    args: argparse.Namespace,
    fetcher: Fetcher,
    overrides: dict,
    uploader: Callable[[str, NormalizedLogo], str],
) -> list[Outcome]:
    """Process selected companies one at a time against production.

    No row is locked while network calls run, and each company is committed on
    its own, so a concurrent crawl never waits on this worker. A dry run writes
    nothing at all and ends its read transaction after every company.
    """
    from sqlalchemy import select

    from core.models import Company, Opportunity
    from pipeline import revalidate

    started = time.monotonic()
    selected = select_companies(session, args, overrides)
    guard = GenericGuard()
    for company in session.scalars(select(Company).where(Company.logo_status == "found")):
        if company.logo_url:
            evidence = company.logo_evidence or {}
            guard.add(evidence.get("sha256"), evidence.get("domain"), company.name)
    session.rollback()  # end the read transaction before any network call
    robots: dict[str, RobotFileParser] = {}
    outcomes: dict[int, Outcome] = {}
    changed: set[int] = set()
    for company_id, _count in selected:
        if time.monotonic() - started >= args.time_budget_min * 60:
            print("Time budget reached")
            break
        company = session.get(Company, company_id, populate_existing=True)
        if company is None:
            continue
        override = overrides.get(company.slug)
        needs_override = override_needed(company, override)
        if not needs_override and (company.logo_url is not None or company.logo_status == "manual"):
            session.rollback()
            continue
        old_url = company.logo_url
        name, slug, domain = company.name, company.slug, company.domain

        def cache_lookup(
            candidate_domain: str, company_id: int = company_id
        ) -> tuple[str, dict] | None:
            owner = domain_owner(session, company_id, candidate_domain)
            if owner is not None and owner.logo_url:
                return owner.logo_url, dict(owner.logo_evidence or {})
            return None

        try:
            result = resolve_logo(
                fetcher,
                name,
                domain,
                company.logo_hint_url,
                override,
                lambda company_id=company_id: recent_listing_texts(session, company_id),
                robots,
                cache_lookup,
                lambda candidate, name=name: guard_outcome(guard, candidate, name),
            )
        except Exception as exc:
            # Exception text can contain credential-bearing URLs. Log only its type.
            result = Outcome(
                evidence={"reason": f"error ({type(exc).__name__})", "domain": domain},
                error=True,
            )

        if args.dry_run:
            new_url = "(would store)" if result.found else old_url
            session.rollback()
        else:
            try:
                with session.begin_nested():
                    apply_outcome(session, company, result, override, uploader)
                    session.flush()
                session.commit()
                new_url = company.logo_url
            except Exception as exc:
                # Upload or write failed: leave the row untouched so the next run retries it.
                session.rollback()
                result = Outcome(
                    evidence={"reason": f"save failed ({type(exc).__name__})", "domain": domain},
                    error=True,
                )
                new_url = old_url
        outcomes[company_id] = result
        if old_url != new_url:
            changed.add(company_id)
        prefix = "Would change" if args.dry_run else "Processed"
        print(
            f"{prefix} {slug} status={'manual' if override else result.status} "
            f"source={result.source} domain={result.domain or domain} "
            f"sha256={result.evidence.get('sha256', '')} {result.evidence.get('reason', '')}"
        )

    if args.dry_run:
        for result in outcomes.values():
            if result.evidence.get("sha256") in guard.rejected:
                result.status = "rejected_generic"
                result.source = None
                result.logo = None
                result.cached_url = None
    else:
        changed.update(generic_post_pass(session, guard.rejected))
        session.commit()
        for company_id, result in outcomes.items():
            company = session.get(Company, company_id)
            if company is not None and company.logo_status == "rejected_generic":
                result.status = "rejected_generic"
                result.source = None
                result.logo = None
                result.cached_url = None
        if changed:
            slugs = session.scalars(
                select(Opportunity.slug).where(
                    Opportunity.company_id.in_(changed), *active_filters()
                )
            ).all()
            revalidate.notify_changed(slugs)
    print_summary(list(outcomes.values()), started)
    print_missing(session)
    session.rollback()
    return list(outcomes.values())


def report_row(company: dict, result: Outcome) -> dict:
    score = result.evidence.get("candidates", {}).get(result.domain, {})
    return {
        "slug": company["slug"],
        "name": company["name"],
        "active_count": company["active_count"],
        "status": result.status,
        "source": result.source or "",
        "domain": result.domain or "",
        "score": score.get("score", ""),
        "signals": ", ".join(score.get("signals", [])),
        **{key: result.evidence.get(key, "") for key in ("image_url", "width", "height", "sha256")},
        "reason": result.evidence.get("reason", ""),
    }


def write_report(directory: Path, reviews: list[tuple[dict, Outcome]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    rows = [report_row(company, result) for company, result in reviews]
    fields = (
        "slug name active_count status source domain score signals image_url width height sha256 reason"
    ).split()
    with (directory / "decisions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    accepted, misses = [], []
    for row, (_company, result) in zip(rows, reviews):
        safe = {key: html.escape(str(value), quote=True) for key, value in row.items()}
        if result.status == "found" and result.logo:
            png = base64.b64encode(result.logo.png_bytes).decode("ascii")
            accepted.append(
                f'<article><img alt="" src="data:image/png;base64,{png}">'
                f'<h2>{safe["name"]}</h2><p>Active listings {safe["active_count"]}</p>'
                f'<p>{safe["domain"]}</p><p>{safe["source"]}</p>'
                f'<p>Score {safe["score"]}</p><p>{safe["signals"]}</p></article>'
            )
        else:
            misses.append(
                f'<tr><td>{safe["name"]}</td><td>{safe["active_count"]}</td>'
                f'<td>{safe["status"]}</td><td>{safe["reason"]}</td></tr>'
            )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Company logo review</title><style>"
        "body{font:16px system-ui;margin:24px;background:#f5f6f8;color:#17202a}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}"
        "article{padding:16px;background:white;border:1px solid #ccd2da;overflow-wrap:anywhere}"
        "img{width:128px;height:128px}h2{font-size:18px}p{margin:6px 0}"
        "table{border-collapse:collapse;width:100%;background:white}"
        "th,td{text-align:left;border:1px solid #ccd2da;padding:8px}</style>"
        '<h1>Accepted logos</h1><div class="grid">'
        + "".join(accepted)
        + "</div><h1>Misses</h1><table><thead><tr><th>Company</th><th>Active listings</th>"
        "<th>Status</th><th>Reason</th></tr></thead><tbody>"
        + "".join(misses)
        + "</tbody></table></html>"
    )
    (directory / "contact-sheet.html").write_text(page, encoding="utf-8")


def run_offline(args: argparse.Namespace, fetcher: Fetcher) -> list[Outcome]:
    started = time.monotonic()
    companies = json.loads(args.from_api_json.read_text(encoding="utf-8"))
    companies.sort(key=lambda row: (-row["active_count"], row["slug"]))
    companies = companies[: args.limit]
    guard = GenericGuard()
    robots: dict[str, RobotFileParser] = {}
    reviews: list[tuple[dict, Outcome]] = []
    for company in companies:
        if time.monotonic() - started >= args.time_budget_min * 60:
            print("Time budget reached")
            break
        try:
            result = resolve_logo(
                fetcher,
                company["name"],
                company.get("domain"),
                None,
                None,
                lambda: [],
                robots,
                lambda _domain: None,
                lambda candidate, name=company["name"]: guard_outcome(guard, candidate, name),
            )
        except Exception as exc:
            result = Outcome(evidence={"reason": f"error ({type(exc).__name__})"}, error=True)
        reviews.append((company, result))
    # The third occurrence also invalidates earlier accepted images in the report.
    for _company, result in reviews:
        if result.evidence.get("sha256") in guard.rejected:
            result.status = "rejected_generic"
            result.source = None
            result.logo = None
            result.cached_url = None
            result.evidence["reason"] = "same image on at least 3 independent groups"
    write_report(args.report, reviews)
    print_summary([result for _, result in reviews], started)
    for label, subset in (("top 100", reviews[:100]), ("whole run", reviews)):
        count = sum(result.found for _, result in subset)
        listings = sum(company["active_count"] for company, _ in subset)
        covered = sum(company["active_count"] for company, result in subset if result.found)
        print(
            f"Coverage {label} {count}/{len(subset)} companies, {covered}/{listings} active listings"
        )
    print("Top companies still missing logos")
    for company, result in [(co, r) for co, r in reviews if not r.found][:25]:
        print(
            f"{company['active_count']:5} {company['name']} [{result.status}] {result.evidence.get('reason', '')}"
        )
    return [result for _, result in reviews]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--time-budget-min", type=float, default=45)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recheck-days", type=int, default=30)
    parser.add_argument("--from-api-json", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = parser.parse_args(argv)
    if args.from_api_json and not args.report:
        parser.error("--report is required with --from-api-json")
    if args.limit < 0 or args.time_budget_min <= 0 or args.recheck_days < 0:
        parser.error("limit/recheck-days must be nonnegative and time-budget-min must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.from_api_json:
        with httpx.Client() as client:
            run_offline(args, HttpFetcher(client))
        return 0
    settings: Settings = get_settings()
    if not args.dry_run and not logo_storage_configured(settings):
        missing = [name.upper() for name in STORAGE_FIELDS if not getattr(settings, name).strip()]
        print(f"Logo storage is not configured. Missing settings {', '.join(missing)}")
        return 2
    overrides = load_overrides(args.overrides)
    # Keep these imports below the offline return and the storage preflight.
    from sqlalchemy.orm import Session

    from core.db import make_engine

    engine = make_engine()
    try:
        storage = None if args.dry_run else s3_client(settings)
        with Session(engine) as session, httpx.Client() as client:
            run_db(
                session,
                args,
                HttpFetcher(client),
                overrides,
                lambda slug, logo: upload_logo(storage, settings, slug, logo),
            )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
