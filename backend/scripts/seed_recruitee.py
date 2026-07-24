from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company, Source

SOURCE_SLUG = "recruitee"
COMPANIES = [
    {
        "slug": "sendcloud",
        "name": "Sendcloud",
        "name_normalized": "sendcloud",
        "domain": "sendcloud.com",
        "ats_type": SOURCE_SLUG,
        "ats_board_id": "sendcloud",
    },
    {
        "slug": "effectory",
        "name": "Effectory",
        "name_normalized": "effectory",
        "domain": "effectory.com",
        "ats_type": SOURCE_SLUG,
        "ats_board_id": "effectory",
    },
]


def upsert_source(session: Session) -> bool:
    source = (
        session.query(Source)
        .filter(or_(Source.slug == SOURCE_SLUG, Source.adapter_key == SOURCE_SLUG))
        .first()
    )
    created = source is None

    if source is None:
        source = Source(
            slug=SOURCE_SLUG,
            name="Recruitee",
            type="ats",
            adapter_key=SOURCE_SLUG,
            crawl_tier=1,
            enabled=True,
            legal_status="ok",
        )
        session.add(source)
    else:
        source.slug = SOURCE_SLUG
        source.name = "Recruitee"
        source.type = "ats"
        source.adapter_key = SOURCE_SLUG
        source.crawl_tier = 1
        source.enabled = True
        source.legal_status = "ok"

    return created


def upsert_company(session: Session, company_data: dict[str, str]) -> bool:
    company = (
        session.query(Company)
        .filter(
            or_(
                Company.slug == company_data["slug"],
                (
                    (Company.ats_type == SOURCE_SLUG)
                    & (Company.ats_board_id == company_data["ats_board_id"])
                ),
            )
        )
        .first()
    )
    created = company is None

    if company is None:
        company = Company(**company_data)
        session.add(company)
    else:
        company.slug = company_data["slug"]
        company.name = company_data["name"]
        company.name_normalized = company_data["name_normalized"]
        company.domain = company_data["domain"]
        company.ats_type = company_data["ats_type"]
        company.ats_board_id = company_data["ats_board_id"]

    return created


def main() -> None:
    engine = make_engine()
    source_created = False
    companies_created = 0
    companies_present = 0

    with Session(engine) as session:
        source_created = upsert_source(session)

        for company_data in COMPANIES:
            if upsert_company(session, company_data):
                companies_created += 1
            else:
                companies_present += 1

        session.commit()

    source_status = "created" if source_created else "present"
    print(
        "Recruitee seed complete: "
        f"source={source_status}; "
        f"companies_created={companies_created}; "
        f"companies_present={companies_present}"
    )


if __name__ == "__main__":
    main()
