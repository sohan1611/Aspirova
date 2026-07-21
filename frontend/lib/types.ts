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

export interface OpportunityListItem {
  slug: string;
  title: string;
  company: CompanySummary | null;
  category: string | null;
  source: string | null;
  meta?: Record<string, unknown> | null;
  location: string | null;
  country: string | null;
  is_remote: boolean | null;
  deadline: string | null;
  deadline_confidence: "explicit" | "inferred" | "unknown";
  posted_at: string | null;
  last_seen_at: string;
  is_hidden: boolean;
}

export type BookmarkStage =
  | "saved"
  | "applied"
  | "interviewing"
  | "offer"
  | "archived";

export type BugReportCategory = "dead_link" | "wrong_info" | "bug" | "other";

export interface BugReportRequest {
  category: BugReportCategory;
  message: string;
  opportunity_slug?: string;
  page_url?: string;
  contact_email?: string;
}

export interface BugReportResponse {
  ok: boolean;
}

export type SavedOpportunityItem = OpportunityListItem & {
  bookmark_status: BookmarkStage;
};

export interface SavedSearchParams {
  q?: string | null;
  category?: "internship" | "job" | "hackathon" | "competition" | null;
  kind?: "roles" | "competitions" | null;
  remote?: boolean | null;
  scope?: "abroad" | "domestic" | "both" | null;
  country?: string | null;
  source?: "direct" | "unstop" | "remoteok" | "devpost" | null;
  experience?: "early" | null;
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

export interface OpportunityDetail extends OpportunityListItem {
  description_raw: string;
  summary: string | null;
  apply_url: string;
  reopen_estimate?: {
    window: string;
    basis: "historical" | "curated";
    note: string;
  } | null;
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

export interface UpgradeResult {
  status: "upgraded";
  amount_paise: number;
  waived?: boolean;
}

export interface UpgradePaymentRequired {
  status: "payment_required";
  amount_paise: number;
  razorpay_order_id: string;
  razorpay_key_id: string;
}

export interface AccountMe {
  email: string | null;
  display_name: string | null;
  college: string | null;
  graduation_year: number | null;
  created_at: string;
  invite_code: string | null;
  notification_prefs: Record<string, boolean>;
  plan: PlanState;
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
  opportunity_title: string | null;
  company_name: string | null;
  created_at: string;
  read: boolean;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  unread: number;
}
