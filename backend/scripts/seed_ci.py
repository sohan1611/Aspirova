"""Seed the deterministic read-API corpus used by CI.

The rows below are intentionally small and idempotent: they satisfy the
read-only API integration tests without requiring CI to query production.
Usage: uv run python -m scripts.seed_ci
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company, Opportunity

# (slug, name, domain, global_rank, prestige_rank)
COMPANIES = [
    ("ci-seed-acme", "CI Seed Alpha Labs", "ciseed-alpha.example.com", 101, 11),
    ("ci-seed-globex", "CI Seed Bravo Systems", "ciseed-bravo.example.com", 202, 22),
    ("ci-seed-initech", "CI Seed Charlie Works", "ciseed-charlie.example.com", 303, 33),
]

# (slug, company_slug, title, category, location, country, is_remote, primary_source)
OPPORTUNITIES = [
    (
        "ci-seed-software-engineer-intern",
        "ci-seed-acme",
        "Software Engineer Intern",
        "internship",
        "Remote",
        "US",
        True,
        "greenhouse",
    ),
    (
        "ci-seed-software-engineer",
        "ci-seed-acme",
        "Software Engineer",
        "job",
        "New York, NY",
        "US",
        False,
        "greenhouse",
    ),
    (
        "ci-seed-senior-software-engineer",
        "ci-seed-acme",
        "Senior Software Engineer",
        "job",
        "Austin, TX",
        "US",
        False,
        "greenhouse",
    ),
    (
        "ci-seed-backend-software-engineer",
        "ci-seed-acme",
        "Backend Software Engineer",
        "job",
        "Remote",
        "US",
        True,
        "greenhouse",
    ),
    (
        "ci-seed-frontend-software-engineer",
        "ci-seed-globex",
        "Frontend Software Engineer",
        "job",
        "San Francisco, CA",
        "US",
        False,
        "lever",
    ),
    (
        "ci-seed-platform-software-engineer",
        "ci-seed-globex",
        "Platform Software Engineer",
        "job",
        "Seattle, WA",
        "US",
        False,
        "lever",
    ),
    (
        "ci-seed-full-stack-software-engineer",
        "ci-seed-globex",
        "Full Stack Software Engineer",
        "job",
        "Remote",
        "US",
        True,
        "lever",
    ),
    (
        "ci-seed-mobile-software-engineer",
        "ci-seed-globex",
        "Mobile Software Engineer",
        "job",
        "Boston, MA",
        "US",
        False,
        "lever",
    ),
    (
        "ci-seed-new-grad-software-engineer",
        "ci-seed-initech",
        "Software Engineer, New Grad",
        "job",
        "Chicago, IL",
        "US",
        False,
        "ashby",
    ),
    (
        "ci-seed-infrastructure-software-engineer",
        "ci-seed-initech",
        "Software Engineer, Infrastructure",
        "job",
        "Remote",
        "US",
        True,
        "ashby",
    ),
    (
        "ci-seed-data-platform-software-engineer",
        "ci-seed-initech",
        "Software Engineer, Data Platform",
        "job",
        "Denver, CO",
        "US",
        False,
        "ashby",
    ),
    (
        "ci-seed-developer-experience-software-engineer",
        "ci-seed-initech",
        "Software Engineer, Developer Experience",
        "job",
        "Remote",
        "US",
        True,
        "ashby",
    ),
    (
        "ci-seed-data-engineer",
        "ci-seed-acme",
        "Data Engineer",
        "job",
        "New York, NY",
        "US",
        False,
        "greenhouse",
    ),
    (
        "ci-seed-product-analyst",
        "ci-seed-globex",
        "Product Analyst",
        "job",
        "San Francisco, CA",
        "US",
        False,
        "lever",
    ),
    (
        "ci-seed-security-research-intern",
        "ci-seed-initech",
        "Security Research Intern",
        "internship",
        "Remote",
        "US",
        True,
        "ashby",
    ),
]


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        companies: dict[str, Company] = {}
        companies_created = 0

        for slug, name, domain, global_rank, prestige_rank in COMPANIES:
            company = session.scalar(select(Company).where(Company.slug == slug))
            if company is None:
                company = Company(
                    slug=slug,
                    name=name,
                    name_normalized=name.lower(),
                    domain=domain,
                    global_rank=global_rank,
                    prestige_rank=prestige_rank,
                )
                session.add(company)
                companies_created += 1
            companies[slug] = company

        session.flush()

        opportunities_created = 0
        seen_at = datetime.now(UTC)
        for (
            slug,
            company_slug,
            title,
            category,
            location,
            country,
            is_remote,
            primary_source,
        ) in OPPORTUNITIES:
            if session.scalar(select(Opportunity).where(Opportunity.slug == slug)) is not None:
                continue

            company = companies[company_slug]
            session.add(
                Opportunity(
                    slug=slug,
                    company_id=company.id,
                    title=title,
                    title_normalized=title.lower(),
                    category=category,
                    primary_source=primary_source,
                    location=location,
                    country=country,
                    is_remote=is_remote,
                    description_raw=f"{title} opportunity at {company.name}.",
                    summary=f"Join {company.name} as a {title}.",
                    apply_url=f"https://{company.domain}/careers/{slug}",
                    posted_at=seen_at,
                    deadline=None,
                    deadline_confidence="unknown",
                    is_hidden=False,
                    status="active",
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                )
            )
            opportunities_created += 1

        # The database trigger fills search_tsv during this flush; do not set it here.
        session.flush()
        session.commit()

        if companies_created == 0 and opportunities_created == 0:
            print("ci seed: already seeded")
        else:
            print(
                "ci seed: "
                f"{companies_created} companies created, "
                f"{opportunities_created} opportunities created"
            )


if __name__ == "__main__":
    main()
