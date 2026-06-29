"""Seed verified Greenhouse companies (Doc 04 sec 11: onboarding playbook).

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


def seed() -> None:
    engine = make_engine()
    with Session(engine) as session:
        source = session.scalar(select(Source).where(Source.slug == "greenhouse"))
        if source is None:
            source = Source(
                slug="greenhouse",
                name="Greenhouse",
                type="ats",
                base_url="https://boards-api.greenhouse.io",
                crawl_tier=1,
                adapter_key="greenhouse",
            )
            session.add(source)
            print("created source: greenhouse")
        else:
            print("source already exists: greenhouse")

        created, updated = 0, 0
        for board_token, name, domain in GREENHOUSE_COMPANIES:
            slug = board_token
            company = session.scalar(select(Company).where(Company.slug == slug))
            if company is None:
                session.add(
                    Company(
                        slug=slug,
                        name=name,
                        name_normalized=name.lower(),
                        domain=domain,
                        ats_type="greenhouse",
                        ats_board_id=board_token,
                    )
                )
                created += 1
            else:
                company.ats_type = "greenhouse"
                company.ats_board_id = board_token
                company.domain = domain
                updated += 1

        session.commit()
        print(f"companies: {created} created, {updated} updated")


if __name__ == "__main__":
    seed()
