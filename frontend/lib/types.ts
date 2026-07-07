// Mirrors backend/api/schemas.py - keep these in sync by hand (Phase 1 has
// no shared schema generation yet).

export interface CompanySummary {
  slug: string;
  name: string;
  domain: string | null;
  logo_url: string | null;
}

export interface CompanyListItem {
  slug: string;
  name: string;
  active_count: number;
}

export interface OpportunityListItem {
  slug: string;
  title: string;
  company: CompanySummary | null;
  category: string | null;
  location: string | null;
  is_remote: boolean | null;
  deadline: string | null;
  deadline_confidence: "explicit" | "inferred" | "unknown";
  posted_at: string | null;
  last_seen_at: string;
  is_hidden: boolean;
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

export interface ReferralMe {
  invite_code: string;
  referral_count: number;
  reward_active_until: string | null;
}

export interface ReferralClaimResult {
  referred: boolean;
  reason: string;
}
