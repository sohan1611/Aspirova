"""Seed verified companies across all registered ATS adapters (Doc 04 sec
11: onboarding playbook; Doc handoffs/PHASE-2-HANDOFF.md sec 5, Part 2.5
adds Lever + Ashby to the original Greenhouse-only seed).

Board tokens are DATA, never hardcoded in adapter code - this script is the
one place new ATS-covered companies get added. Every token below was checked
live (HTTP 200 + non-empty jobs array) before being added; do not add a token
without verifying it first, and remove any that start 404ing.

Idempotent - safe to re-run. Usage: uv run python -m scripts.seed_companies
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company, Source

# (board_token, company_name, domain) - verified live against
# https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
GREENHOUSE_COMPANIES = [
    ("stripe", "Stripe", "stripe.com"),
    ("airbnb", "Airbnb", "airbnb.com"),
    ("discord", "Discord", "discord.com"),
    ("robinhood", "Robinhood", "robinhood.com"),
    ("figma", "Figma", "figma.com"),
    ("coinbase", "Coinbase", "coinbase.com"),
    ("asana", "Asana", "asana.com"),
    ("brex", "Brex", "brex.com"),
    ("pinterest", "Pinterest", "pinterest.com"),
    ("reddit", "Reddit", "reddit.com"),
    ("cloudflare", "Cloudflare", "cloudflare.com"),
    ("gitlab", "GitLab", "gitlab.com"),
]

# (board_token, company_name, domain) - verified live against
# https://api.lever.co/v0/postings/{token}?mode=json
LEVER_COMPANIES = [
    ("weride", "WeRide", "weride.ai"),
    ("angellist", "AngelList", "angellist.com"),
    ("wealthfront", "Wealthfront", "wealthfront.com"),
]

# (board_token, company_name, domain) - verified live against
# https://api.ashbyhq.com/posting-api/job-board/{token}
ASHBY_COMPANIES = [
    ("linear", "Linear", "linear.app"),
    ("notion", "Notion", "notion.so"),
    ("ashby", "Ashby", "ashbyhq.com"),
]

# adapter_key -> (source slug/name/base_url, company list)
_ADAPTER_SOURCES: dict[str, tuple[str, str, str, list[tuple[str, str, str]]]] = {
    "greenhouse": (
        "greenhouse",
        "Greenhouse",
        "https://boards-api.greenhouse.io",
        GREENHOUSE_COMPANIES,
    ),
    "lever": ("lever", "Lever", "https://api.lever.co", LEVER_COMPANIES),
    "ashby": ("ashby", "Ashby", "https://api.ashbyhq.com", ASHBY_COMPANIES),
}

# Aggregator sources (Doc 04 sec 1: best-effort tier) have no fixed
# per-company list - crawl_aggregator resolves/creates each listing's
# Company row dynamically (pipeline/company_resolution.py) - so they're
# seeded as a bare Source row only, separately from _ADAPTER_SOURCES.
_AGGREGATOR_SOURCES: dict[str, tuple[str, str, str]] = {
    "remoteok": ("remoteok", "RemoteOK", "https://remoteok.com"),
}


def seed() -> None:
    engine = make_engine()
    with Session(engine) as session:
        total_created, total_updated = 0, 0

        for adapter_key, (slug, name, base_url, companies) in _ADAPTER_SOURCES.items():
            source = session.scalar(select(Source).where(Source.slug == slug))
            if source is None:
                source = Source(
                    slug=slug,
                    name=name,
                    type="ats",
                    base_url=base_url,
                    crawl_tier=1,
                    adapter_key=adapter_key,
                )
                session.add(source)
                print(f"created source: {slug}")
            else:
                print(f"source already exists: {slug}")

            for board_token, company_name, domain in companies:
                # Bare board_token, matching the already-seeded Greenhouse
                # companies exactly (Doc 08: never change an existing
                # identifier scheme without a real migration) - a
                # namespaced slug would silently duplicate every company
                # already seeded in production instead of updating it,
                # since this script's own idempotency depends on the slug
                # it looks up matching what's already there.
                company_slug = board_token
                company = session.scalar(select(Company).where(Company.slug == company_slug))
                if company is None:
                    session.add(
                        Company(
                            slug=company_slug,
                            name=company_name,
                            name_normalized=company_name.lower(),
                            domain=domain,
                            ats_type=adapter_key,
                            ats_board_id=board_token,
                        )
                    )
                    total_created += 1
                else:
                    company.ats_type = adapter_key
                    company.ats_board_id = board_token
                    company.domain = domain
                    total_updated += 1

        for adapter_key, (slug, name, base_url) in _AGGREGATOR_SOURCES.items():
            source = session.scalar(select(Source).where(Source.slug == slug))
            if source is None:
                session.add(
                    Source(
                        slug=slug,
                        name=name,
                        type="aggregator",
                        base_url=base_url,
                        crawl_tier=1,
                        adapter_key=adapter_key,
                    )
                )
                print(f"created source: {slug}")
            else:
                print(f"source already exists: {slug}")

        session.commit()
        print(f"companies: {total_created} created, {total_updated} updated")


if __name__ == "__main__":
    seed()
