"""Integration tests for pipeline/company_resolution.py against the real
dev database (needed by the aggregator - Doc handoffs/PHASE-2-HANDOFF.md
sec 2/5). Every test runs inside a transaction that is rolled back at the
end (Doc 08: tests must not pollute shared state).
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from pipeline.company_resolution import resolve_company


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_resolve_company_creates_a_new_row_when_none_matches(db_session: Session) -> None:
    company = resolve_company(db_session, "Totally Unique Test Co XYZ123")

    assert company.id is not None
    assert company.name == "Totally Unique Test Co XYZ123"
    assert company.name_normalized == "totally unique test co xyz123"


def test_resolve_company_cleans_name_before_normalizing(db_session: Session) -> None:
    company = resolve_company(db_session, "  SÃ£o   Paulo Test Company XYZ123  ")

    assert company.name == "São Paulo Test Company XYZ123"
    assert company.name_normalized == "são paulo test company xyz123"


def test_resolve_company_matches_an_existing_row_by_normalized_name(db_session: Session) -> None:
    existing = models.Company(
        slug="acme-existing-test",
        name="Acme Corp",
        name_normalized="acme",  # normalize_company_name strips the "Corp" suffix
    )
    db_session.add(existing)
    db_session.flush()

    resolved = resolve_company(db_session, "Acme Corp")

    assert resolved.id == existing.id


def test_resolve_company_is_idempotent_across_repeated_calls(db_session: Session) -> None:
    first = resolve_company(db_session, "Repeat Test Company Inc")
    db_session.flush()
    second = resolve_company(db_session, "Repeat Test Company Inc")

    assert first.id == second.id

    count = db_session.scalar(
        select(func.count())
        .select_from(models.Company)
        .where(models.Company.name_normalized == "repeat test company")
    )
    assert count == 1


def test_resolve_company_treats_legal_suffix_and_case_variants_as_the_same_company(
    db_session: Session,
) -> None:
    first = resolve_company(db_session, "Widget Makers LLC")
    db_session.flush()
    second = resolve_company(db_session, "WIDGET MAKERS, LLC.")

    assert first.id == second.id
