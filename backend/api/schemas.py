"""API response schemas. Outbound apply_url is always present on detail
responses - the canonical opportunity page links to the real source, never
mirrors it (Doc 01 sec 7 R1, Doc 04 sec 10)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

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
    closed_at: datetime | None
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
            closed_at=o.closed_at,
            deadline_confidence=o.deadline_confidence,
            posted_at=o.posted_at,
            last_seen_at=o.last_seen_at,
            is_hidden=o.is_hidden,
            meta=o.meta,
        )


class ProgrammeEditionItem(BaseModel):
    year: int
    status: str
    opens_at: datetime | None
    closes_at: datetime | None
    source_url: str | None
    verified_at: datetime | None
    notes: str | None

    @classmethod
    def from_model(cls, edition: "models.ProgrammeEdition") -> "ProgrammeEditionItem":
        # Status is reported exactly as stored; never infer "open" from dates.
        return cls(
            year=edition.year,
            status=edition.status,
            opens_at=edition.opens_at,
            closes_at=edition.closes_at,
            source_url=edition.source_url,
            verified_at=edition.verified_at,
            notes=edition.notes,
        )


class ProgrammeListItem(BaseModel):
    slug: str
    name: str
    organiser: str
    category: str
    country: str | None
    url: str
    description: str | None
    typical_window: str | None
    tags: list[str] = []
    match_count: int = 0
    current_edition: ProgrammeEditionItem | None

    @classmethod
    def from_model(
        cls,
        programme: "models.Programme",
        *,
        current_edition: "models.ProgrammeEdition | None" = None,
        match_count: int = 0,
    ) -> "ProgrammeListItem":
        return cls(
            slug=programme.slug,
            name=programme.name,
            organiser=programme.organiser,
            category=programme.category,
            country=programme.country,
            url=programme.url,
            description=programme.description,
            typical_window=programme.typical_window,
            tags=list(programme.tags or []),
            match_count=match_count,
            current_edition=(
                ProgrammeEditionItem.from_model(current_edition)
                if current_edition is not None
                else None
            ),
        )


class ProgrammeDetail(ProgrammeListItem):
    eligibility: str | None
    editions: list[ProgrammeEditionItem]

    @classmethod
    def from_model(cls, programme: "models.Programme") -> "ProgrammeDetail":
        editions = sorted(programme.editions, key=lambda edition: edition.year, reverse=True)
        current_edition = next(
            (edition for edition in editions if edition.status != "discontinued"),
            None,
        )
        base = ProgrammeListItem.from_model(programme, current_edition=current_edition)
        return cls(
            **base.model_dump(),
            eligibility=programme.eligibility,
            editions=[ProgrammeEditionItem.from_model(edition) for edition in editions],
        )


class SavedOpportunityItem(OpportunityListItem):
    bookmark_status: str

    @classmethod
    def from_models(cls, opportunity: "models.Opportunity", status: str) -> "SavedOpportunityItem":
        base = OpportunityListItem.from_model(opportunity)
        return cls(**base.model_dump(), bookmark_status=status)


class NotificationItem(BaseModel):
    id: int
    type: str
    title: str
    body: str
    opportunity_slug: str | None
    opportunity_title: str | None
    company_name: str | None
    created_at: datetime
    read: bool


class NotificationsResponse(BaseModel):
    items: list[NotificationItem]
    unread: int


class BookmarkStatusUpdate(BaseModel):
    status: Literal["saved", "applied", "interviewing", "offer", "archived"]


class SavedSearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = None
    category: str | None = None
    kind: str | None = None
    remote: bool | None = None
    scope: str | None = None
    country: str | None = None
    source: str | None = None
    experience: str | None = None


class SavedSearchCreate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    params: SavedSearchParams
    alerts_enabled: bool = True


class SavedSearchItem(BaseModel):
    id: int
    name: str | None
    params: SavedSearchParams
    alerts_enabled: bool
    last_alerted_at: datetime | None
    created_at: datetime

    @field_serializer("params")
    def serialize_params(self, params: SavedSearchParams) -> dict[str, str | bool]:
        return params.model_dump(exclude_none=True)


class SavedSearchAlertsUpdate(BaseModel):
    alerts_enabled: bool


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
    skills: list[str] = []
    reopen_estimate: ReopenEstimateSchema | None = None
    is_stale: bool = False
    # Used by the frontend to explain staleness honestly when posted_at is
    # missing - never presented as a posted date, only as "first found".
    first_seen_at: datetime

    @classmethod
    def from_model(
        cls,
        o: "models.Opportunity",
        *,
        reopen_estimate: ReopenEstimateSchema | None = None,
        is_stale: bool = False,
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
            closed_at=o.closed_at,
            deadline_confidence=o.deadline_confidence,
            posted_at=o.posted_at,
            last_seen_at=o.last_seen_at,
            is_hidden=o.is_hidden,
            meta=o.meta,
            description_raw=o.description_raw or "",
            summary=o.summary,
            apply_url=o.apply_url,
            skills=list(o.skills or []),
            reopen_estimate=reopen_estimate,
            is_stale=is_stale,
            first_seen_at=o.first_seen_at,
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


class ProgrammeListResponse(BaseModel):
    items: list[ProgrammeListItem]
    total: int
    page: int
    limit: int


class TrendingResponse(BaseModel):
    items: list[OpportunityListItem]


class StatsResponse(BaseModel):
    opportunities: int
    companies: int
    sources: int
    updated_at: datetime | None


class FacetOption(BaseModel):
    value: str
    label: str
    count: int


class FacetsResponse(BaseModel):
    companies: list[str]
    locations: list[str]
    company_counts: list[FacetOption] = []
    location_counts: list[FacetOption] = []
    comp_types: list[FacetOption] = []
    registrations: list[FacetOption] = []
    deadline_within: list[FacetOption] = []
    organiser_types: list[FacetOption] = []
    modes: list[FacetOption] = []


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
    cancel_at_period_end: bool = False


class AccountMe(BaseModel):
    email: str | None
    display_name: str | None
    college: str | None
    graduation_year: int | None
    created_at: datetime
    invite_code: str | None
    notification_prefs: dict[str, bool]
    field_profile: dict | None
    skills: list | None
    exposure: dict | None
    resume: dict | None = None
    plan: PlanState


class AccountUpdate(BaseModel):
    display_name: str | None = None
    college: str | None = None
    graduation_year: int | None = None
    notification_prefs: dict[str, bool] | None = None
    field_profile: dict | None = None
    skills: list | None = None
    exposure: dict | None = None
    resume: dict | None = None

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

    @field_validator("field_profile", mode="before")
    @classmethod
    def validate_field_profile(cls, value: object) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("field_profile must be an object")

        stream = value.get("stream")
        if isinstance(stream, str):
            stream = stream.strip() or None
            if stream is not None and len(stream) > 64:
                raise ValueError("field_profile.stream must be at most 64 characters")
        elif stream is not None:
            stream = None

        return {
            "stream": stream,
            "divisions": cls._normalize_field_profile_keys(value.get("divisions")),
            "interests": cls._normalize_field_profile_keys(value.get("interests")),
        }

    @staticmethod
    def _normalize_field_profile_keys(value: object) -> list[str]:
        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            key = item.strip()
            if not key:
                continue
            if len(key) > 64:
                raise ValueError("field_profile keys must be at most 64 characters")
            if key in seen:
                continue
            seen.add(key)
            normalized.append(key)
            if len(normalized) == 64:
                break

        return normalized

    @field_validator("skills", mode="before")
    @classmethod
    def validate_skills(cls, value: object) -> list[dict[str, str]] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("skills must be a list")

        normalized: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            name = name.strip()
            if not 1 <= len(name) <= 80:
                continue

            source = item.get("source", "manual")
            if not isinstance(source, str) or source not in {"resume", "manual"}:
                continue

            normalized.append({"name": name, "source": source})
            if len(normalized) == 100:
                break

        return normalized

    @field_validator("exposure", mode="before")
    @classmethod
    def validate_exposure(cls, value: object) -> dict[str, str | None] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("exposure must be an object")

        return {
            "experience": cls._normalize_exposure_text(value.get("experience")),
            "notes": cls._normalize_exposure_text(value.get("notes")),
        }

    @staticmethod
    def _normalize_exposure_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None

        normalized = value.strip()
        if len(normalized) > 2_000:
            raise ValueError("exposure text must be at most 2000 characters")
        return normalized or None


class WaitlistSignupRequest(BaseModel):
    email: str


class WaitlistSignupResponse(BaseModel):
    ok: bool = True


class BugReportRequest(BaseModel):
    category: str
    message: str
    opportunity_slug: str | None = None
    page_url: str | None = None
    contact_email: str | None = None


class BugReportResponse(BaseModel):
    ok: bool = True
