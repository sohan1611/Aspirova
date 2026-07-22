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
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    global_rank: Mapped[int | None] = mapped_column(Integer)
    prestige_rank: Mapped[int | None] = mapped_column(Integer)
    is_dream_eligible: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="company")

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
        Index("ix_companies_global_rank", "global_rank"),
        Index("ix_companies_prestige_rank", "prestige_rank"),
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
    primary_source: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(2))
    is_remote: Mapped[bool | None] = mapped_column(Boolean)
    description_raw: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column()
    deadline: Mapped[datetime | None] = mapped_column()
    meta: Mapped[dict | None] = mapped_column(JSONB)
    deadline_confidence: Mapped[str] = mapped_column(Text, server_default="unknown")
    is_hidden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    first_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    # Populated by a DB trigger (title + company + summary + description), not the ORM. See migration.
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    company: Mapped["Company | None"] = relationship(back_populates="opportunities")

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
        Index("ix_opportunities_primary_source", "primary_source"),
        Index("ix_opportunities_country", "country"),
    )


class OpportunityViewCount(Base):
    """Hot cumulative view counters kept off the wide opportunities row."""

    __tablename__ = "opportunity_view_counts"

    opportunity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    views: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
    invite_code: Mapped[str | None] = mapped_column(Text, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    college: Mapped[str | None] = mapped_column(Text)
    graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    notification_prefs: Mapped[dict | None] = mapped_column()
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
    status: Mapped[str] = mapped_column(Text, server_default=text("'saved'"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class SavedSearch(Base):
    """A user's reusable feed-filter state; alert delivery is added separately."""

    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    alerts_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (Index("ix_saved_searches_user_created_at", "user_id", "created_at"),)


class Plan(Base):
    """The single source of feature gating (Doc 03 sec 4.1, Doc 08 sec 1:
    'MUST drive plan gating from plans.features via a single can(user,
    feature) helper'). Prices are stored in paise (integer), never a
    float, to avoid rounding errors (Doc 06 sec 1)."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    billing: Mapped[str | None] = mapped_column(Text)
    features: Mapped[dict] = mapped_column(nullable=False)
    # Populated once the matching Razorpay-side Plan object exists
    # (scripts/setup_razorpay_plans.py) - null for the free plan, which
    # never goes through Razorpay at all.
    razorpay_plan_id: Mapped[str | None] = mapped_column(Text)


class Subscription(Base):
    """A user's subscription to a plan (Doc 03 sec 4.1). status mirrors
    Razorpay's subscription lifecycle: 'active'|'past_due'|'canceled'|
    'trialing' - updated only by the Razorpay webhook handler
    (api/payments.py), never guessed client-side."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    plan_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    razorpay_sub_id: Mapped[str | None] = mapped_column(Text, unique=True)
    current_period_end: Mapped[datetime | None] = mapped_column()
    cancel_at_period_end: Mapped[bool] = mapped_column(server_default=text("false"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (Index("ix_subscriptions_user_status", "user_id", "status"),)


class SubscriptionUpgrade(Base):
    """An auditable one-time payment record for a subscription plan change."""

    __tablename__ = "subscription_upgrades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id"), nullable=False
    )
    from_plan_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("plans.id"), nullable=False)
    to_plan_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("plans.id"), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'same_period_upgrade'")
    )
    razorpay_order_id: Mapped[str | None] = mapped_column(Text, unique=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class DreamCompany(Base):
    """A user's tracked company for instant alerts (Doc 03 sec 4.2),
    limited per plan via plans.features.dream_companies_limit + can()."""

    __tablename__ = "dream_companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_dream_companies_user_company"),
    )


class Notification(Base):
    """Log + dedup of every notification sent (Doc 03 sec 4.3) - the
    (user_id, type, sent_at) index backs both frequency caps (has this
    user already gotten a digest today?) and suppression (has this exact
    user+opportunity instant alert already gone out?)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"))
    channel: Mapped[str] = mapped_column(Text, server_default="email")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column()
    read_at: Mapped[datetime | None] = mapped_column()
    meta: Mapped[dict | None] = mapped_column()

    __table_args__ = (Index("ix_notifications_user_type_sent", "user_id", "type", "sent_at"),)


class AiUsage(Base):
    """One row per generation or embedding call, including local stub calls."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    feature: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    est_cost: Mapped[float] = mapped_column(Float, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ResumeProfile(Base):
    """A cached resume embedding; matching itself never calls a generation model."""

    __tablename__ = "resume_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_resume_profiles_user_version"),
    )


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


class BugReport(Base):
    """A visitor-submitted issue report, optionally tied to a user and opportunity."""

    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    opportunity_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("opportunities.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'open'"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (Index("ix_bug_reports_status_created_at", "status", "created_at"),)
