"""API response schemas. Outbound apply_url is always present on detail
responses - the canonical opportunity page links to the real source, never
mirrors it (Doc 01 sec 7 R1, Doc 04 sec 10)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core import models


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    domain: str | None = None
    logo_url: str | None = None


class CompanyListItem(BaseModel):
    slug: str
    name: str
    domain: str | None = None
    logo_url: str | None = None
    active_count: int


class SitemapOpportunity(BaseModel):
    slug: str
    last_seen_at: datetime


class SitemapCompany(BaseModel):
    slug: str


class OpportunityListItem(BaseModel):
    slug: str
    title: str
    company: CompanySummary | None
    category: str | None
    source: str | None = None
    location: str | None
    country: str | None = None
    is_remote: bool | None
    deadline: datetime | None
    deadline_confidence: str
    posted_at: datetime | None
    last_seen_at: datetime
    is_hidden: bool
    meta: dict | None = None

    @field_validator("location")
    @classmethod
    def _clean_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        seen: set[str] = set()
        parts: list[str] = []
        for raw in value.split(","):
            segment = raw.strip()
            if not segment:
                continue
            key = segment.casefold()
            if key in seen:
                continue
            seen.add(key)
            parts.append(segment)
        return ", ".join(parts) or None

    @classmethod
    def from_model(cls, o: "models.Opportunity") -> "OpportunityListItem":
        return cls(
            slug=o.slug,
            title=o.title,
            company=CompanySummary.model_validate(o.company) if o.company else None,
            category=o.category,
            source=o.primary_source,
            location=o.location,
            country=o.country,
            is_remote=o.is_remote,
            deadline=o.deadline,
            deadline_confidence=o.deadline_confidence,
            posted_at=o.posted_at,
            last_seen_at=o.last_seen_at,
            is_hidden=o.is_hidden,
            meta=o.meta,
        )


class ResumeUploadRequest(BaseModel):
    resume_text: str


class ResumeUploadResponse(BaseModel):
    version: int


ReferralClaimReason = Literal["ok", "already_referred", "self_referral", "unknown_code"]


class ReferralMeResponse(BaseModel):
    invite_code: str
    referral_count: int
    reward_active_until: datetime | None


class ReferralClaimRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class ReferralClaimResponse(BaseModel):
    referred: bool
    reason: ReferralClaimReason


class MatchItem(BaseModel):
    opportunity: OpportunityListItem
    score: float


class CopilotRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class CopilotSource(BaseModel):
    slug: str
    title: str
    company: str | None


class CopilotResponse(BaseModel):
    answer: str
    sources: list[CopilotSource]
    cached: bool
    degraded: bool


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
            source=o.primary_source,
            location=o.location,
            country=o.country,
            is_remote=o.is_remote,
            deadline=o.deadline,
            deadline_confidence=o.deadline_confidence,
            posted_at=o.posted_at,
            last_seen_at=o.last_seen_at,
            is_hidden=o.is_hidden,
            meta=o.meta,
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


class StatsResponse(BaseModel):
    opportunities: int
    companies: int
    sources: int
    updated_at: datetime | None


class CompanyPage(BaseModel):
    company: CompanySummary
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


class PlanState(BaseModel):
    key: str
    price_paise: int
    billing: str | None
    features: dict
    status: str
    current_period_end: datetime | None


class AccountMe(BaseModel):
    email: str | None
    display_name: str | None
    college: str | None
    graduation_year: int | None
    created_at: datetime
    invite_code: str | None
    notification_prefs: dict[str, bool]
    plan: PlanState


class AccountUpdate(BaseModel):
    display_name: str | None = None
    college: str | None = None
    graduation_year: int | None = None
    notification_prefs: dict[str, bool] | None = None

    @field_validator("display_name", "college")
    @classmethod
    def clean_profile_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        max_length = 80 if info.field_name == "display_name" else 120
        if len(normalized) > max_length:
            raise ValueError(f"{info.field_name} must be at most {max_length} characters")
        return normalized

    @field_validator("graduation_year")
    @classmethod
    def validate_graduation_year(cls, value: int | None) -> int | None:
        if value is not None and not 2000 <= value <= 2100:
            raise ValueError("graduation_year must be between 2000 and 2100")
        return value

    @field_validator("notification_prefs", mode="before")
    @classmethod
    def validate_notification_prefs(cls, value):
        if value is None:
            return None
        if not isinstance(value, dict) or any(
            not isinstance(item_value, bool) for item_value in value.values()
        ):
            raise ValueError("notification_prefs values must be bool")
        return value


class WaitlistSignupRequest(BaseModel):
    email: str


class WaitlistSignupResponse(BaseModel):
    ok: bool = True
