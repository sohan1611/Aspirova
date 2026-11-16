"""Blank source eligibility is unknown, including on repeat imports."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.hiring_calendar import CALENDAR_META, ROWS, SLUG_BY_ROW_ID
from core.models import Programme
from scripts.import_calendar import _import_row


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection)
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.mark.parametrize("row_id", ["OPP-202", "OPP-210", "OPP-213", "OPP-216", "OPP-218"])
@pytest.mark.parametrize("blank", [None, "", " \n\t "])
def test_import_normalizes_blank_eligibility_and_repairs_existing_text(
    db_session, monkeypatch, row_id, blank
):
    slug = SLUG_BY_ROW_ID[row_id]
    monkeypatch.setitem(ROWS, row_id, {**ROWS[row_id], "target_batch_eligibility": blank})
    _import_row(db_session, slug, CALENDAR_META[slug])
    item = db_session.scalar(select(Programme).where(Programme.slug == slug))
    assert item.eligibility is None
    item.eligibility = "   "
    db_session.flush()
    _import_row(db_session, slug, CALENDAR_META[slug])
    db_session.refresh(item)
    assert item.eligibility is None
