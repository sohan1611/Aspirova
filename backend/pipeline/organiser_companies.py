"""Link authored organisers using the existing exact company resolver."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.external_companies import EXTERNAL_COMPANIES
from core.models import Programme
from pipeline.company_resolution import resolve_company


def link_programme_company(
    session: Session, programme: Programme, *, evidence_changed: bool = False
) -> None:
    company = resolve_company(session, programme.organiser)
    new_link = programme.company_id != company.id
    programme.company_id = company.id
    programme.company = company
    if (
        (new_link or evidence_changed)
        and company.logo_url is None
        and company.logo_status != "manual"
    ):
        company.logo_status = None


def link_organiser_companies(session: Session) -> None:
    """Backfill existing registry rows and include companies without crawled jobs.

    A programme URL may identify a programme's own brand or a partner, so it
    contributes listing evidence in the worker rather than a trusted domain.
    Only the external-company registry supplies explicit official domains.
    The caller owns the transaction. Dry runs skip this write pass.
    """
    for entry in EXTERNAL_COMPANIES:
        resolve_company(session, entry["name"], entry["domain"])
    for programme in session.scalars(
        select(Programme).where(Programme.is_active.is_(True)).order_by(Programme.id)
    ):
        if programme.company_id is None:
            link_programme_company(session, programme)
    session.flush()
