import json
from pathlib import Path

import pytest

from core.models import Company
from pipeline.normalize import normalize_company_name
from scripts import seed_boards_batch


class _ScalarResult:
    def __init__(self, companies: list[Company]) -> None:
        self._companies = companies

    def all(self) -> list[Company]:
        return list(self._companies)


class FakeSession:
    """Small in-memory session seam: batch tests must never need a real database."""

    def __init__(self, companies: list[Company] | None = None) -> None:
        self.companies = list(companies or [])
        self.added: list[Company] = []
        self.commits = 0

    def scalars(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(self.companies)

    def add(self, company: Company) -> None:
        self.added.append(company)
        self.companies.append(company)

    def commit(self) -> None:
        self.commits += 1


def _candidate(
    *,
    company_name: str = "Test Board Co",
    ats_type: str = "lever",
    board_token: str = "test-board-co",
    domain: str | None = "test-board.example",
) -> seed_boards_batch.BoardCandidate:
    return seed_boards_batch.BoardCandidate(
        company_name=company_name,
        ats_type=ats_type,
        board_token=board_token,
        domain=domain,
    )


def _ok(candidate: seed_boards_batch.BoardCandidate, listings_count: int = 1):
    return seed_boards_batch.Verification(
        candidate=candidate,
        accepted=True,
        health="ok",
        listings_count=listings_count,
    )


def test_broken_candidate_is_rejected_and_never_written() -> None:
    candidate = _candidate()
    session = FakeSession()

    summary = seed_boards_batch.run_batch(
        session,
        [candidate],
        apply=True,
        verifier=lambda value: seed_boards_batch.Verification(
            candidate=value,
            accepted=True,
            health="broken",
            listings_count=0,
            reason="health=broken",
        ),
        verify_workers=1,
    )

    assert summary.verified == []
    assert summary.rejected[0].reason == "health=broken"
    assert session.added == []
    assert session.commits == 0


def test_healthy_empty_board_is_accepted() -> None:
    candidate = _candidate()
    session = FakeSession()

    summary = seed_boards_batch.run_batch(
        session,
        [candidate],
        apply=True,
        verifier=lambda value: _ok(value, listings_count=0),
        verify_workers=1,
    )

    assert summary.verified[0].listings_count == 0
    assert summary.inserted == [candidate]
    assert len(session.added) == 1


def test_raised_adapter_is_rejected_without_aborting_the_batch() -> None:
    broken = _candidate(company_name="Raised", board_token="raised-board")
    healthy = _candidate(company_name="Healthy", board_token="healthy-board")
    session = FakeSession()

    def verifier(candidate: seed_boards_batch.BoardCandidate) -> seed_boards_batch.Verification:
        if candidate == broken:
            raise RuntimeError("adapter boom")
        return _ok(candidate)

    summary = seed_boards_batch.run_batch(
        session,
        [broken, healthy],
        apply=True,
        verifier=verifier,
        verify_workers=1,
    )

    assert summary.rejected[0].reason == "raised RuntimeError: adapter boom"
    assert summary.inserted == [healthy]
    assert [company.slug for company in session.added] == ["healthy-board"]


def test_existing_unboarded_company_is_attached_not_duplicated() -> None:
    candidate = _candidate(company_name="Existing Co", board_token="existing-board")
    existing = Company(
        slug="existing-co-legacy",
        name="Existing Co",
        name_normalized=normalize_company_name("Existing Co"),
        domain=None,
        ats_type=None,
        ats_board_id=None,
    )
    session = FakeSession([existing])

    summary = seed_boards_batch.run_batch(
        session,
        [candidate],
        apply=True,
        verifier=_ok,
        verify_workers=1,
    )

    assert summary.attached == [candidate]
    assert session.added == []
    assert existing.ats_type == "lever"
    assert existing.ats_board_id == "existing-board"
    assert existing.domain == "test-board.example"


def test_existing_different_board_is_conflict_and_is_untouched() -> None:
    candidate = _candidate(company_name="Existing Co", board_token="lever-board")
    existing = Company(
        slug="existing-co-legacy",
        name="Existing Co",
        name_normalized=normalize_company_name("Existing Co"),
        domain="existing.example",
        ats_type="greenhouse",
        ats_board_id="greenhouse-board",
    )
    session = FakeSession([existing])

    summary = seed_boards_batch.run_batch(
        session,
        [candidate],
        apply=True,
        verifier=_ok,
        verify_workers=1,
    )

    assert len(summary.conflicts) == 1
    assert session.added == []
    assert session.commits == 0
    assert (existing.ats_type, existing.ats_board_id) == ("greenhouse", "greenhouse-board")


def test_dry_run_writes_nothing() -> None:
    candidate = _candidate()
    session = FakeSession()

    summary = seed_boards_batch.run_batch(
        session,
        [candidate],
        apply=False,
        verifier=_ok,
        verify_workers=1,
    )

    assert summary.would_insert == [candidate]
    assert session.added == []
    assert session.commits == 0


def test_apply_is_idempotent_on_rerun() -> None:
    candidate = _candidate()
    session = FakeSession()

    first = seed_boards_batch.run_batch(
        session,
        [candidate],
        apply=True,
        verifier=_ok,
        verify_workers=1,
    )
    second = seed_boards_batch.run_batch(
        session,
        [candidate],
        apply=True,
        verifier=_ok,
        verify_workers=1,
    )

    assert first.inserted == [candidate]
    assert second.unchanged == [candidate]
    assert len(session.companies) == 1
    assert session.commits == 1


def test_candidate_file_is_structurally_valid() -> None:
    candidates = seed_boards_batch.load_candidates()

    supported_ats_types = {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "keka",
        "workable",
        "recruitee",
    }
    seen_pairs: set[tuple[str, str]] = set()

    assert candidates

    for candidate in candidates:
        assert candidate.ats_type in supported_ats_types
        assert isinstance(candidate.board_token, str)
        assert candidate.board_token
        assert not any(character.isspace() for character in candidate.board_token)
        assert isinstance(candidate.company_name, str)
        assert candidate.company_name.strip()
        if candidate.domain is not None:
            assert isinstance(candidate.domain, str)
            assert candidate.domain.strip()

        pair = (candidate.ats_type, candidate.board_token)
        assert pair not in seen_pairs
        seen_pairs.add(pair)


def test_candidate_loader_rejects_duplicate_board_pairs(tmp_path: Path) -> None:
    candidate = {
        "company_name": "Duplicate Co",
        "ats_type": "lever",
        "board_token": "duplicate-co",
        "domain": None,
    }
    path = tmp_path / "company_boards.json"
    path.write_text(json.dumps([candidate, candidate]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate candidate board pair"):
        seed_boards_batch.load_candidates(path)
