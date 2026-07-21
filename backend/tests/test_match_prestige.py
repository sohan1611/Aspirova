import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from core import models
from scripts.match_prestige import match_prestige


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


def _write_prestige_fixture(path: Path, suffix: str) -> None:
    rows = [
        {
            "prestige_rank": 12,
            "name": "Domain Matched",
            "domain": f"domain-matched-{suffix}.example",
        },
        {
            "prestige_rank": 42,
            "name": f"Name Only Holdings {suffix}",
            "domain": None,
        },
        {
            "prestige_rank": 5,
            "name": f"Domain Beats Name {suffix}",
            "domain": None,
        },
        {
            "prestige_rank": 80,
            "name": "Unrelated Domain Row",
            "domain": f"domain-beats-{suffix}.example",
        },
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_match_prestige_assigns_precise_domain_and_name_matches(
    db_session: Session,
    tmp_path: Path,
) -> None:
    prestige_path = tmp_path / "prestige_companies.json"
    suffix = str(uuid.uuid4())
    _write_prestige_fixture(prestige_path, suffix)
    domain_match = models.Company(
        slug=f"prestige-domain-match-{suffix}",
        name=f"Local Domain Match {suffix}",
        domain=f"DOMAIN-MATCHED-{suffix}.EXAMPLE",
    )
    name_match = models.Company(
        slug=f"prestige-name-match-{suffix}",
        name=f"Name Only Holdings {suffix} LLC",
    )
    non_match = models.Company(
        slug=f"prestige-non-match-{suffix}",
        name=f"Definitely Not Prestige {suffix}",
        domain=f"not-prestige-{suffix}.example",
    )
    domain_beats_name = models.Company(
        slug=f"prestige-domain-beats-name-{suffix}",
        name=f"Domain Beats Name {suffix}",
        domain=f"domain-beats-{suffix}.example",
    )
    db_session.add_all([domain_match, name_match, non_match, domain_beats_name])
    db_session.flush()

    result = match_prestige(db_session, prestige_path=prestige_path, batch_size=2)

    assert result["ranked"] >= 3
    assert domain_match.prestige_rank == 12
    assert name_match.prestige_rank == 42
    assert non_match.prestige_rank is None
    assert domain_beats_name.prestige_rank == 80
