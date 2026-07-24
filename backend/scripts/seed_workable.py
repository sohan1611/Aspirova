from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company, Source


def main() -> None:
    engine = make_engine()

    with Session(engine) as session:
        source, source_created = upsert_source(session)
        company, company_created = upsert_company(session)

        if not source_created:
            source.enabled = True
            source.legal_status = "ok"

        session.commit()

        created_count = int(source_created) + int(company_created)
        present_count = 2 - created_count
        print(
            "Seeded Workable: "
            f"created={created_count}, already_present={present_count}, "
            f"source_id={source.id}, company_id={company.id}"
        )


def upsert_source(session: Session) -> tuple[Source, bool]:
    source = session.execute(
        select(Source)
        .where(or_(Source.slug == "workable", Source.adapter_key == "workable"))
        .limit(1)
    ).scalar_one_or_none()

    if source is not None:
        return source, False

    source = Source(
        slug="workable",
        name="Workable",
        type="ats",
        adapter_key="workable",
        crawl_tier=1,
        enabled=True,
        legal_status="ok",
    )
    session.add(source)
    return source, True


def upsert_company(session: Session) -> tuple[Company, bool]:
    company = session.execute(
        select(Company)
        .where(
            or_(
                Company.slug == "huggingface",
                and_(
                    Company.ats_type == "workable",
                    Company.ats_board_id == "huggingface",
                ),
            )
        )
        .limit(1)
    ).scalar_one_or_none()

    if company is not None:
        return company, False

    company = Company(
        slug="huggingface",
        name="Hugging Face",
        name_normalized="hugging face",
        domain="huggingface.co",
        ats_type="workable",
        ats_board_id="huggingface",
    )
    session.add(company)
    return company, True


if __name__ == "__main__":
    main()
