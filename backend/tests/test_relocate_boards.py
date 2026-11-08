"""Relocation verification fixtures; no HTTP and no database connection."""

import pytest

from core.adapters import RawListing
from core.models import Company
from scripts import relocate_boards as relocation
from scripts.seed_boards_batch import BoardCandidate, Verification, verify_candidate


@pytest.fixture
def company():
    return Company(
        slug="ledger", name="Ledger", domain="ledger.com", ats_type="lever", ats_board_id="ledger"
    )


@pytest.fixture
def session(company):
    class MemorySession:
        def scalar(self, statement):
            return company

    return MemorySession()


def _verification(
    candidate, *, text="Join Ledger building hardware wallets.", health="ok", count=1
):
    job = RawListing(
        source_slug="ashby",
        external_id="fixture-1",
        source_url="https://jobs.ashbyhq.com/ledger/fixture-1",
        content_hash="fixture",
        raw_payload={
            "descriptionPlain": text,
            "jobUrl": "https://jobs.ashbyhq.com/ledger/fixture-1",
        },
    )
    return Verification(candidate, True, health, count, listings=(job,) if count else ())


def test_shared_verifier_retains_posting_evidence(monkeypatch):
    from scripts import seed_boards_batch

    candidate = BoardCandidate("Ledger", "ashby", "ledger", "ledger.com")
    fixture = _verification(candidate)

    class Adapter:
        def __init__(self, **kwargs):
            pass

        def fetch(self):
            return fixture.listings

        def health(self):
            return "ok"

    monkeypatch.setitem(seed_boards_batch.ATS_ADAPTERS, "ashby", Adapter)
    verified = verify_candidate(candidate)
    assert verified.accepted
    assert verified.listings == fixture.listings


def test_relocation_is_dry_by_default_then_idempotent(session, company):
    move = [row for row in relocation.RELOCATIONS if row.company_slug == "ledger"]
    calls = []

    def verifier(candidate):
        calls.append(candidate)
        return _verification(candidate)

    assert relocation.relocate_boards(session, relocations=move, verifier=verifier) == {
        "ledger": "would relocate"
    }
    assert company.ats_type == "lever"
    assert relocation.relocate_boards(session, relocations=move, verifier=verifier, apply=True) == {
        "ledger": "relocated"
    }
    assert company.ats_type == "ashby"
    assert company.ats_board_id == "ledger"
    assert relocation.relocate_boards(session, relocations=move, verifier=verifier, apply=True) == {
        "ledger": "unchanged"
    }
    assert len(calls) == 2


@pytest.mark.parametrize(
    "text,health,count",
    [
        ("Different Accounting Company is hiring.", "ok", 1),
        ("Join Ledger.", "degraded", 1),
        ("Join Ledger.", "ok", 0),
        ("Ledgerly is hiring.", "ok", 1),
    ],
)
def test_rejects_collision_empty_or_unhealthy_target(session, company, text, health, count):
    move = [row for row in relocation.RELOCATIONS if row.company_slug == "ledger"]
    result = relocation.relocate_boards(
        session,
        relocations=move,
        apply=True,
        verifier=lambda candidate: _verification(candidate, text=text, health=health, count=count),
    )
    assert result["ledger"].startswith("rejected:")
    assert company.ats_type == "lever"


def test_first_party_domain_in_posting_is_identity_evidence(company):
    candidate = BoardCandidate("Ledger", "ashby", "ledger", "ledger.com")
    assert relocation.posting_confirms_company(
        _verification(candidate, text="Our team: https://www.ledger.com/about"), company
    )


def test_unexpected_current_pair_is_a_conflict_without_network(session, company):
    company.ats_board_id = "unreviewed"
    move = [row for row in relocation.RELOCATIONS if row.company_slug == "ledger"]

    def verifier(candidate):
        raise AssertionError("must not fetch an unexpected board")

    result = relocation.relocate_boards(session, relocations=move, apply=True, verifier=verifier)
    assert result["ledger"].startswith("conflict:")
    assert company.ats_board_id == "unreviewed"
