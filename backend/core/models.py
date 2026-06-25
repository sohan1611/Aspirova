"""SQLAlchemy models — Phase-1 subset of the canonical schema (docs/03-data-architecture.md).

Migrations (Alembic) are the schema contract (Doc 08 sec 2). This module is the
ORM mirror of that contract; do not let the two drift apart.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict: JSONB,
    }


class Source(Base):
    """A crawlable platform/site (Doc 03 3.1, Doc 04)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    crawl_tier: Mapped[int | None] = mapped_column(SmallInteger)
    adapter_key: Mapped[str | None] = mapped_column(Text)
    robots_policy: Mapped[str] = mapped_column(Text, server_default="respect")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    legal_status: Mapped[str] = mapped_column(Text, server_default="ok")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Company(Base):
    """Normalized canonical company (Doc 03 3.2). ats_board_id is DATA, never hardcoded (Doc 04 sec 11)."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    ats_type: Mapped[str | None] = mapped_column(Text)
    ats_board_id: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
    is_dream_eligible: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index(
            "ix_companies_name_normalized_trgm",
            "name_normalized",
            postgresql_using="gin",
            postgresql_ops={"name_normalized": "gin_trgm_ops"},
        ),
        Index(
            "ix_companies_domain_unique",
            "domain",
            unique=True,
            postgresql_where=text("domain IS NOT NULL"),
        ),
    )


class RawListing(Base):
    """Exactly what we crawled — audit + dedup evidence, never overwritten (Doc 03 3.3)."""

    __tablename__ = "raw_listings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column()
    crawled_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    processed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_listings_source_external"),
        Index(
            "ix_raw_listings_unprocessed", "processed", postgresql_where=text("processed = false")
        ),
    )


class Opportunity(Base):
    """THE canonical, user-facing record — one row per real opportunity (Doc 03 3.4)."""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_normalized: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    is_remote: Mapped[bool | None] = mapped_column(Boolean)
    description_raw: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column()
    deadline: Mapped[datetime | None] = mapped_column()
    deadline_confidence: Mapped[str] = mapped_column(Text, server_default="unknown")
    is_hidden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    first_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    # Populated by a DB trigger (title + company + summary + description), not the ORM. See migration.
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("ix_opportunities_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_opportunities_title_normalized_trgm",
            "title_normalized",
            postgresql_using="gin",
            postgresql_ops={"title_normalized": "gin_trgm_ops"},
        ),
        Index(
            "ix_opportunities_active_deadline",
            "status",
            "deadline",
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_opportunities_company_active",
            "company_id",
            postgresql_where=text("status = 'active'"),
        ),
    )


class OpportunitySource(Base):
    """Every place a canonical opportunity was found — dedup provenance (Doc 03 3.5)."""

    __tablename__ = "opportunity_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_listing_id: Mapped[int | None] = mapped_column(ForeignKey("raw_listings.id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "opportunity_id", "source_id", "source_url", name="uq_opportunity_sources"
        ),
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(Text)


class OpportunityTag(Base):
    __tablename__ = "opportunity_tags"

    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class User(Base):
    """Mirrors Supabase Auth users (id matches auth.users.id once Auth is wired in Step 8)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    college: Mapped[str | None] = mapped_column(Text)
    graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    referred_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class Bookmark(Base):
    __tablename__ = "bookmarks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class CrawlRun(Base):
    """Operational observability for every crawl (Doc 03 5.1, Doc 04 sec 7)."""

    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str | None] = mapped_column(Text)
    listings_found: Mapped[int | None] = mapped_column(Integer)
    new_opps: Mapped[int | None] = mapped_column(Integer)
    errors: Mapped[int | None] = mapped_column(Integer)
    log: Mapped[dict | None] = mapped_column()


class CrawlJob(Base):
    """Postgres-as-queue for the crawl runner; claimed via SELECT ... FOR UPDATE SKIP LOCKED (Doc 03 5.1)."""

    __tablename__ = "crawl_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    claimed_at: Mapped[datetime | None] = mapped_column()
    locked_by: Mapped[str | None] = mapped_column(Text)


class SourceState(Base):
    """Change-detection hashes — gates downstream parse/dedup/enrich (Doc 03 5.2, Doc 04 sec 6)."""

    __tablename__ = "source_state"

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    page_key: Mapped[str] = mapped_column(Text, primary_key=True)
    last_content_hash: Mapped[str | None] = mapped_column(Text)
    last_crawled_at: Mapped[datetime | None] = mapped_column()
