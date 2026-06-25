"""Structural checks on the Phase-1 schema contract. No DB connection required
(see Doc 08: keep tests fast; the live migration itself is verified manually
against the dev database as part of each schema change)."""

from core.models import Base

EXPECTED_TABLES = {
    "sources",
    "companies",
    "raw_listings",
    "opportunities",
    "opportunity_sources",
    "tags",
    "opportunity_tags",
    "users",
    "bookmarks",
    "crawl_runs",
    "crawl_jobs",
    "source_state",
}


def test_phase1_tables_registered() -> None:
    assert EXPECTED_TABLES.issubset(Base.metadata.tables.keys())


def test_opportunities_has_canonical_columns() -> None:
    columns = {c.name for c in Base.metadata.tables["opportunities"].columns}
    assert {"slug", "company_id", "title", "apply_url", "deadline", "status", "search_tsv"}.issubset(
        columns
    )


def test_raw_listings_dedup_uniqueness_constraint_exists() -> None:
    raw_listings = Base.metadata.tables["raw_listings"]
    unique_cols = {
        tuple(col.name for col in constraint.columns)
        for constraint in raw_listings.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("source_id", "external_id") in unique_cols


def test_opportunity_sources_provenance_uniqueness_constraint_exists() -> None:
    opportunity_sources = Base.metadata.tables["opportunity_sources"]
    unique_cols = {
        tuple(col.name for col in constraint.columns)
        for constraint in opportunity_sources.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("opportunity_id", "source_id", "source_url") in unique_cols
