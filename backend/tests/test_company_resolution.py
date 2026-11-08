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


def test_resolve_company_creates_row_with_clean_domain_and_logo_hint(db_session: Session) -> None:
    company = resolve_company(
        db_session,
        "Logo Metadata Test XYZ123",
        " https://WWW.logo-metadata-xyz123.example/jobs ",
        logo_hint_url="https://images.example/logo.png",
    )
    db_session.refresh(company)
    assert company.domain == "logo-metadata-xyz123.example"
    assert company.logo_hint_url == "https://images.example/logo.png"
    assert company.logo_status is None
    assert company.logo_source is None
    assert company.logo_checked_at is None
    assert company.logo_evidence is None


@pytest.mark.parametrize("domain", ["https://jobs.lever.co/acme", "127.0.0.1", "localhost"])
def test_resolve_company_rejects_invalid_new_domain(db_session: Session, domain: str) -> None:
    company = resolve_company(db_session, "Logo Invalid Domain Test XYZ123", domain)
    assert company.domain is None


@pytest.mark.parametrize(
    "name, domain",
    [
        ("Google", "google.com"),
        ("Devfolio", "devfolio.co"),
        ("Hacker Earth", "hackerearth.com"),
    ],
)
@pytest.mark.parametrize("existing_row", [False, True])
def test_resolve_company_allows_platform_company_own_domain(
    db_session: Session, name: str, domain: str, existing_row: bool
) -> None:
    if existing_row:
        resolve_company(db_session, name)

    company = resolve_company(db_session, name, domain)
    db_session.flush()
    db_session.refresh(company)

    assert company.domain == domain


def test_resolve_company_creates_new_row_without_taken_domain(db_session: Session) -> None:
    owner = resolve_company(
        db_session, "Logo New Domain Owner Test XYZ123", "logo-new-domain-owner-xyz123.example"
    )

    company = resolve_company(
        db_session,
        "Logo New Domain Conflict Test XYZ123",
        f"https://www.{owner.domain}/jobs",
        logo_hint_url="https://images.example/new.png",
    )
    db_session.refresh(company)

    assert company.id is not None
    assert company.id != owner.id
    assert company.domain is None
    assert company.logo_hint_url == "https://images.example/new.png"
    assert owner.domain == "logo-new-domain-owner-xyz123.example"


@pytest.mark.parametrize("status", [None, "not_found", "ambiguous", "rejected_generic"])
def test_resolve_company_updates_hint_and_resets_status(db_session: Session, status) -> None:
    existing = resolve_company(
        db_session, "Logo Hint Reset Test XYZ123", logo_hint_url="https://images.example/old.png"
    )
    existing.logo_status = status
    db_session.flush()
    resolved = resolve_company(
        db_session, existing.name, logo_hint_url="https://images.example/new.png"
    )
    db_session.flush()
    db_session.refresh(resolved)
    assert resolved.id == existing.id
    assert resolved.logo_hint_url == "https://images.example/new.png"
    assert resolved.logo_status is None


@pytest.mark.parametrize("hint", [None, "https://images.example/original.png"])
def test_resolve_company_preserves_status_and_hint_without_new_hint(
    db_session: Session, hint
) -> None:
    existing = resolve_company(
        db_session,
        "Logo Unchanged Hint Test XYZ123",
        logo_hint_url="https://images.example/original.png",
    )
    existing.logo_status = "not_found"
    db_session.flush()
    resolved = resolve_company(db_session, existing.name, logo_hint_url=hint)
    assert resolved.logo_hint_url == "https://images.example/original.png"
    assert resolved.logo_status == "not_found"


@pytest.mark.parametrize("status", ["not_found", "ambiguous", "rejected_generic"])
def test_resolve_company_fills_missing_domain_and_resets_status(
    db_session: Session, status: str
) -> None:
    existing = resolve_company(db_session, "Logo Domain Reset Test XYZ123")
    existing.logo_status = status
    db_session.flush()
    resolved = resolve_company(
        db_session, existing.name, "https://www.logo-domain-reset-xyz123.example/careers"
    )
    db_session.flush()
    db_session.refresh(resolved)
    assert resolved.domain == "logo-domain-reset-xyz123.example"
    assert resolved.logo_status is None


def test_resolve_company_preserves_existing_domain(db_session: Session) -> None:
    existing = resolve_company(
        db_session, "Logo Existing Domain Test XYZ123", "logo-original-xyz123.example"
    )
    existing.logo_status = "not_found"
    db_session.flush()
    resolved = resolve_company(db_session, existing.name, "logo-replacement-xyz123.example")
    assert resolved.domain == "logo-original-xyz123.example"
    assert resolved.logo_status == "not_found"


@pytest.mark.parametrize("hint", [None, "https://images.example/new.png"])
def test_resolve_company_does_not_take_another_rows_domain(db_session: Session, hint) -> None:
    owner = resolve_company(
        db_session, "Logo Domain Owner Test XYZ123", "logo-domain-owner-xyz123.example"
    )
    existing = resolve_company(db_session, "Logo Domain Conflict Test XYZ123")
    existing.logo_status = "not_found"
    db_session.flush()
    resolved = resolve_company(
        db_session, existing.name, f"https://www.{owner.domain}/jobs", logo_hint_url=hint
    )
    db_session.flush()
    assert resolved.id == existing.id
    assert resolved.domain is None
    assert resolved.logo_status == (None if hint else "not_found")
    assert resolved.logo_hint_url == hint
    assert owner.domain == "logo-domain-owner-xyz123.example"


def test_resolve_company_rejects_invalid_existing_domain_hint(db_session: Session) -> None:
    existing = resolve_company(db_session, "Logo Invalid Existing Domain Test XYZ123")
    existing.logo_status = "not_found"
    db_session.flush()
    resolved = resolve_company(db_session, existing.name, "https://tenant.github.io/jobs")
    assert resolved.domain is None
    assert resolved.logo_status == "not_found"


@pytest.mark.parametrize("domain", [None, "logo-manual-xyz123.example"])
def test_resolve_company_preserves_manual_hint_and_status(db_session: Session, domain) -> None:
    existing = resolve_company(
        db_session, "Logo Manual Test XYZ123", logo_hint_url="https://images.example/manual.png"
    )
    existing.logo_status = "manual"
    db_session.flush()
    resolved = resolve_company(
        db_session, existing.name, domain, logo_hint_url="https://images.example/new.png"
    )
    db_session.flush()
    db_session.refresh(resolved)
    assert resolved.logo_status == "manual"
    assert resolved.logo_hint_url == "https://images.example/manual.png"
    assert resolved.domain == domain


@pytest.mark.parametrize("status", ["found", "manual"])
def test_resolve_company_never_changes_a_row_with_saved_logo(
    db_session: Session, status: str
) -> None:
    existing = resolve_company(
        db_session, "Logo Saved Test XYZ123", logo_hint_url="https://images.example/original.png"
    )
    existing.logo_url = "https://stored.example/logo.png"
    existing.logo_status = status
    existing.logo_source = "source_payload"
    existing.logo_evidence = {"sha256": "test-saved-logo"}
    db_session.flush()
    before = {
        column.name: getattr(existing, column.name) for column in models.Company.__table__.columns
    }
    resolved = resolve_company(
        db_session,
        existing.name,
        "logo-saved-xyz123.example",
        logo_hint_url="https://images.example/new.png",
    )
    db_session.flush()
    db_session.refresh(resolved)
    assert {
        column.name: getattr(resolved, column.name) for column in models.Company.__table__.columns
    } == before
