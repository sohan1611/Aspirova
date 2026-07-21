"""Offline unit tests for provenance cache-miss handling."""

from types import SimpleNamespace

from core import models
from pipeline.ingest import BoardState, _ensure_provenance


class _ProvenanceSession:
    """Minimal Session fake for _ensure_provenance()."""

    def __init__(self, existing_link: models.OpportunitySource | None) -> None:
        self.existing_link = existing_link
        self.scalar_queries: list[object] = []
        self.added: list[object] = []

    def scalar(self, query: object) -> models.OpportunitySource | None:
        self.scalar_queries.append(query)
        return self.existing_link

    def add(self, value: object) -> None:
        self.added.append(value)


def test_cache_miss_reuses_db_link_and_normalizes_empty_source_url() -> None:
    opportunity = SimpleNamespace(id=101)
    raw_row = SimpleNamespace(id=404)
    existing_link = models.OpportunitySource(
        opportunity_id=opportunity.id,
        source_id=202,
        source_url="",
        raw_listing_id=99,
        is_primary=True,
    )
    session = _ProvenanceSession(existing_link)
    board_state = BoardState()

    _ensure_provenance(
        session,
        board_state,
        opportunity,
        202,
        SimpleNamespace(source_url=None),
        raw_row,
        is_primary=False,
    )

    assert session.added == []
    assert len(session.scalar_queries) == 1
    lookup = str(session.scalar_queries[0])
    lookup_params = session.scalar_queries[0].compile().params
    assert "coalesce(opportunity_sources.source_url" in lookup
    assert sum(value == "" for value in lookup_params.values()) == 2
    assert existing_link.raw_listing_id == raw_row.id
    assert existing_link.is_primary is True
    assert board_state.provenance_by_key[(opportunity.id, 202, "")] is existing_link

    _ensure_provenance(
        session,
        board_state,
        opportunity,
        202,
        SimpleNamespace(source_url=""),
        raw_row,
        is_primary=False,
    )

    assert len(session.scalar_queries) == 1
    assert len(board_state.provenance_by_key) == 1
    assert board_state.provenance_by_key[(opportunity.id, 202, "")] is existing_link


def test_cache_miss_inserts_genuinely_new_provenance_link() -> None:
    opportunity = SimpleNamespace(id=101)
    raw_row = SimpleNamespace(id=404)
    source_url = "https://example.test/listing"
    session = _ProvenanceSession(existing_link=None)
    board_state = BoardState()

    _ensure_provenance(
        session,
        board_state,
        opportunity,
        202,
        SimpleNamespace(source_url=source_url),
        raw_row,
        is_primary=True,
    )

    assert len(session.scalar_queries) == 1
    assert len(session.added) == 1
    link = session.added[0]
    assert isinstance(link, models.OpportunitySource)
    assert link.opportunity_id == opportunity.id
    assert link.source_id == 202
    assert link.source_url == source_url
    assert link.raw_listing_id == raw_row.id
    assert link.is_primary is True
    assert board_state.provenance_by_key[(opportunity.id, 202, source_url)] is link
