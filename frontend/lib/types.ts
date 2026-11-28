import type { AtsResult } from "@/lib/atsScore";
import type { Role } from "@/lib/roleSignalQuery";
import type { FieldProfile } from "@/lib/taxonomy";

// Mirrors backend/api/schemas.py - keep these in sync by hand (Phase 1 has
// no shared schema generation yet).

export interface CompanySummary {
  slug: string;
  name: string;
  domain: string | null;
  logo_url: string | null;
}

export interface CompanyListItem extends CompanySummary {
  active_count: number;
}

export interface ListingSafety {
  kind: "scam" | "recalled";
  note: string;
  source_url: string | null;
  flagged_at: string;
}

export interface RoleLevel {
  level: "internship" | "apprenticeship" | "graduate" | "experienced" | "unknown";
  evidence: string | boolean | null;
  source: "title" | "category" | "eligibility" | "override";
}

export type Stage = "school" | "undergraduate" | "postgraduate" | "doctoral" | "recent_graduate";
export interface EligibilityFact<T> {
  value: T;
  evidence: string;
  source: "title" | "description" | "tags" | "location";
}
export interface EligibilityFacts {
  v: number;
  grad_years?: EligibilityFact<number[]>;
  stages?: EligibilityFact<Stage[]>;
  final_year_only?: EligibilityFact<true>;
  degree_levels?: EligibilityFact<("diploma" | "bachelor" | "master" | "doctorate")[]>;
  college_restriction?: EligibilityFact<true>;
  citizenship?: EligibilityFact<string[]>;
  remote_mode?: EligibilityFact<"remote" | "hybrid" | "onsite">;
  remote_regions?: EligibilityFact<string[]>;
  work_authorization?: EligibilityFact<string[]>;
  visa_sponsorship?: EligibilityFact<boolean>;
  timezones?: EligibilityFact<{ min: number; max: number }>;
}

export interface OpportunityListItem {
  last_verified_at?: string | null;
  freshness?: "fresh" | "stale" | null;
  freshness_reason?: "age" | "verification" | null;
  stale_after_hours?: number | null;
  destination_facts?: DestinationFacts | null;
  eligibility?: EligibilityFacts | null;
  role_level?: RoleLevel;
  status?: string;
  safety?: ListingSafety | null;
  slug: string;
  title: string;
  company: CompanySummary | null;
  category: string | null;
  source: string | null;
  // Role meta.compensation currencies: INR | USD | CAD | AUD | SGD | GBP | EUR.
  meta?: Record<string, unknown> | null;
  location: string | null;
  country: string | null;
  is_remote: boolean | null;
  deadline: string | null;
  closed_at: string | null;
  deadline_confidence: "explicit" | "inferred" | "unknown";
  posted_at: string | null;
  last_seen_at: string;
  is_hidden: boolean;
  summary: string | null;
}

export type BookmarkStage =
  | "saved"
  | "planned"
  | "applied"
  | "assessment"
  | "interviewing"
  | "offer"
  | "rejected"
  | "archived";

export interface BookmarkUpdate {
  status?: BookmarkStage;
  note?: string | null;
  status_date?: string | null;
}

export type BugReportCategory = "dead_link" | "wrong_deadline" | "wrong_company" | "duplicate" | "wrong_info" | "bug" | "other" | "scam";

export interface BugReportRequest {
  category: BugReportCategory;
  message: string;
  opportunity_slug?: string;
  page_url?: string;
  contact_email?: string;
}

export interface BugReportResponse {
  ok: boolean;
  reference: string;
}

export interface ReportStatus {
  reference: string;
  category: BugReportCategory;
  status: "open" | "triaged" | "resolved";
  created_at: string;
  triaged_at: string | null;
  resolved_at: string | null;
  resolution: string | null;
  resolution_note: string | null;
  listing_slug: string | null;
  listing_title: string | null;
}

export type SavedOpportunityItem = OpportunityListItem & {
  bookmark_status: BookmarkStage;
  note: string | null;
  status_date: string | null;
  status_changed_at: string | null;
  apply_url: string;
  destination: ApplyDestination;
};

export interface DreamCompanyItem {
  company: CompanySummary;
  roles: string[];
}

export interface SavedSearchParams {
  grad_year?: number;
  stage?: Stage[];
  eligibility_stated?: boolean;
  visa?: "needs";
  q?: string | null;
  category?: "internship" | "job" | "hackathon" | "competition" | "scholarship" | null;
  kind?: "roles" | "competitions" | null;
  remote?: boolean | null;
  scope?: "abroad" | "domestic" | "both" | null;
  country?: string | null;
  source?: "direct" | "unstop" | "remoteok" | "devpost" | null;
  experience?: "early" | "new_grad" | null;
  location?: string[] | null;
  role?: Role | null;
  paid?: boolean | null;
  min_stipend?: number | null;
  part_time?: boolean | null;
  max_duration?: number | null;
  job_offer?: boolean | null;
  comp_type?: string[] | null;
  registration?: string | null;
  deadline_within?: number | null;
  organiser_type?: string[] | null;
  mode?: string[] | null;
  prize_min?: number | null;
  status?: "open" | "closed" | null;
}

export interface SavedSearchCreate {
  name?: string | null;
  params: SavedSearchParams;
  alerts_enabled?: boolean;
}

export interface SavedSearchItem {
  id: number;
  name: string | null;
  params: SavedSearchParams;
  alerts_enabled: boolean;
  last_alerted_at: string | null;
  created_at: string;
}

export interface MatchItem {
  opportunity: OpportunityListItem;
  score: number;
}

export interface ApplyDestination {
  kind: "company" | "ats" | "job_board" | "event_platform" | "unverified";
  host: string | null;
  label: string | null;
}

export interface DestinationFacts {
  v: number;
  valid: boolean;
  host: string | null;
  domain: string | null;
  type: "employer_ats" | "employer_site" | "aggregator" | "government" | "academic" | "competition_platform" | "unknown";
  employer_verified: boolean;
  aggregator_warning: boolean;
  via: string | null;
  platform?: string | null;
  status: string;
  warnings: string[];
  terminal_host?: string | null;
  terminal_domain?: string | null;
  checked_at?: string | null;
  computed_at?: string | null;
}

export interface ListingCorrection {
  at: string;
  field: string;
  summary: string;
}

export interface OpportunityDetail extends OpportunityListItem {
  corrections?: ListingCorrection[];
  destination?: ApplyDestination;
  description_raw: string;
  apply_url: string;
  skills: string[];
  is_stale: boolean;
  first_seen_at: string;
  reopen_estimate?: {
    window: string;
    basis: "historical" | "curated";
    note: string;
  } | null;
}

export type ProgrammeEditionStatus =
  | "expected"
  | "announced"
  | "open"
  | "closed"
  | "discontinued"
  | (string & {});

export interface ProgrammeEditionItem {
  year: number;
  status: ProgrammeEditionStatus;
  opens_at: string | null;
  closes_at: string | null;
  source_url: string | null;
  verified_at: string | null;
  notes: string | null;
}

export interface ProgrammeListItem {
  slug: string;
  name: string;
  organiser: string;
  company?: CompanySummary | null;
  category: string;
  country: string | null;
  url: string;
  description: string | null;
  typical_window: string | null;
  tags: string[];
  match_count: number;
  current_edition: ProgrammeEditionItem | null;
}

export interface ProgrammeDetail extends ProgrammeListItem {
  eligibility: string | null;
  editions: ProgrammeEditionItem[];
}

export interface CopilotSource {
  slug: string;
  company: string | null;
  title: string;
}

export interface CopilotResponse {
  answer: string;
  sources: CopilotSource[];
  cached: boolean;
  degraded: boolean;
}

export interface FeedResponse {
  items: OpportunityListItem[];
  total: number;
  open_total?: number | null;
  page: number;
  limit: number;
}

export interface ProgrammeListResponse {
  items: ProgrammeListItem[];
  total: number;
  page: number;
  limit: number;
}

export interface TrendingResponse {
  items: OpportunityListItem[];
}

export interface StatsResponse {
  opportunities: number;
  companies: number;
  sources: number;
  updated_at: string | null;
}

export interface FacetOption {
  value: string;
  label: string;
  count: number;
}

export interface Facets {
  companies: string[];
  locations: string[];
  company_counts?: FacetOption[];
  location_counts?: FacetOption[];
  comp_types?: FacetOption[];
  registrations?: FacetOption[];
  deadline_within?: FacetOption[];
  organiser_types?: FacetOption[];
  modes?: FacetOption[];
  statuses?: FacetOption[];
  programme_categories?: FacetOption[];
  programme_fields?: FacetOption[];
  programme_organisers?: FacetOption[];
  programme_institution_types?: FacetOption[];
  programme_statuses?: FacetOption[];
}

export interface CompanyPage {
  company: CompanySummary;
  items: OpportunityListItem[];
  total: number;
  page: number;
  limit: number;
}

export interface SearchResponse {
  items: OpportunityListItem[];
  total: number;
  query: string;
}

export interface PlanPublic {
  key: string;
  price_paise: number;
  billing: "monthly" | "annual" | null;
  features: Record<string, boolean | number | string | null>;
}

export interface PlanState {
  key: string;
  price_paise: number;
  billing: string | null;
  features: Record<string, unknown>;
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export interface ResumeMeta {
  path: string;
  filename: string;
  uploaded_at: string;
  ats: AtsResult;
}

export interface AccountMe {
  email: string | null;
  display_name: string | null;
  college: string | null;
  graduation_year: number | null;
  field_profile: FieldProfile | null;
  skills: { name: string; source: "resume" | "manual" }[] | null;
  exposure: { experience: string | null; notes: string | null } | null;
  resume?: ResumeMeta | null;
  created_at: string;
  invite_code: string | null;
  notification_prefs: Record<string, boolean>;
  plan: PlanState;
  digest_status?: DigestStatus | null;
}

/** The reader's latest daily digest outcome. */
export interface DigestStatus {
  last_sent_at: string | null;
  last_sent_count: number;
  last_attempt_failed: boolean;
  last_sent_counts_by_category: Record<string, number>;
}

/** What the reader's next daily digest would contain if it went out now. */
export interface DigestPreview {
  subject: string | null;
  html: string | null;
  listing_count: number;
  hackathon_count: number;
  window_start: string;
}

export interface AccountUpdate {
  display_name?: string | null;
  college?: string | null;
  graduation_year?: number | null;
  notification_prefs?: Record<string, boolean> | null;
  field_profile?: FieldProfile | null;
  skills?: AccountMe["skills"];
  exposure?: AccountMe["exposure"];
  resume?: ResumeMeta | null;
}

export interface ReferralMe {
  invite_code: string;
  referral_count: number;
  reward_active_until: string | null;
}

export interface ReferralClaimResult {
  referred: boolean;
  reason: string;
}

export interface NotificationItem {
  id: number;
  type: string;
  title: string;
  body: string;
  opportunity_slug: string | null;
  programme_slug?: string | null;
  opportunity_title: string | null;
  company_name: string | null;
  created_at: string;
  read: boolean;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  unread: number;
}

export interface SearchRelatedProgramme {
  entity_type: "programme";
  slug: string; name: string; organiser: string; category: string; category_label: string;
  country: string | null;
  match: "slug" | "acronym" | "name" | "organiser" | "company";
  edition: import("./hiringCalendar").CalendarItem["edition"] | null;
  deadline_rolling: boolean;
  path: string; calendar_path: string; official_url: string;
}

export interface SearchRelatedCompany extends CompanyListItem {
  entity_type: "company";
  match: "exact" | "acronym" | "prefix" | "substring";
  path: string;
}

export interface SearchRelatedResponse {
  q: string;
  programmes: { total: number; items: SearchRelatedProgramme[] };
  companies: { total: number; items: SearchRelatedCompany[] };
}
