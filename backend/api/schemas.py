"""API response schemas. Outbound apply_url is always present on detail
responses - the canonical opportunity page links to the real source, never
mirrors it (Doc 01 sec 7 R1, Doc 04 sec 10)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core import models


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    domain: str | None = None
    logo_url: str | None = None


class OpportunityListItem(BaseModel):
    slug: str
    title: str
    company: CompanySummary | None
    category: str | None
    location: str | None
    is_remote: bool | None
    deadline: datetime | None
    deadline_confidence: str
    posted_at: datetime | None
    last_seen_at: datetime
    is_hidden: bool

    @classmethod
    def from_model(cls, o: "models.Opportunity") -> "OpportunityListItem":
        return cls(
            slug=o.slug,
            title=o.title,
            company=CompanySummary.model_validate(o.company) if o.company else None,
            category=o.category,
            location=o.location,
            is_remote=o.is_remote,
            deadline=o.deadline,
            deadline_confidence=o.deadline_confidence,
            posted_at=o.posted_at,
            last_seen_at=o.last_seen_at,
            is_hidden=o.is_hidden,
        )


class ResumeUploadRequest(BaseModel):
    resume_text: str


class ResumeUploadResponse(BaseModel):
    version: int


class MatchItem(BaseModel):
    opportunity: OpportunityListItem
    score: float


class ReopenEstimateSchema(BaseModel):
    window: str
    basis: Literal["historical", "curated"]
    note: str


class OpportunityDetail(OpportunityListItem):
    description_raw: str
    summary: str | None
    apply_url: str
    reopen_estimate: ReopenEstimateSchema | None = None

    @classmethod
    def from_model(
        cls,
        o: "models.Opportunity",
        *,
        reopen_estimate: ReopenEstimateSchema | None = None,
    ) -> "OpportunityDetail":
        return cls(
            slug=o.slug,
            title=o.title,
            company=CompanySummary.model_validate(o.company) if o.company else None,
            category=o.category,
            location=o.location,
            is_remote=o.is_remote,
            deadline=o.deadline,
            deadline_confidence=o.deadline_confidence,
            posted_at=o.posted_at,
            last_seen_at=o.last_seen_at,
            is_hidden=o.is_hidden,
            description_raw=o.description_raw or "",
            summary=o.summary,
            apply_url=o.apply_url,
            reopen_estimate=reopen_estimate,
        )


class DreamCompanyItem(BaseModel):
    company: CompanySummary

    @classmethod
    def from_company(cls, company: "models.Company") -> "DreamCompanyItem":
        return cls(company=CompanySummary.model_validate(company))


class FeedResponse(BaseModel):
    items: list[OpportunityListItem]
    total: int
    page: int
    limit: int


class SearchResponse(BaseModel):
    items: list[OpportunityListItem]
    total: int
    query: str


class PlanPublic(BaseModel):
    """Public projection of `plans` for the pricing page (Doc handoffs/
    PHASE-2.5-HANDOFF.md sec 3.7) - price_paise/features are read-only
    data here, no gating logic; `can()` remains the single gating seam
    server-side."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    price_paise: int
    billing: str | None
    features: dict


class WaitlistSignupRequest(BaseModel):
    email: str


class WaitlistSignupResponse(BaseModel):
    ok: bool = True
