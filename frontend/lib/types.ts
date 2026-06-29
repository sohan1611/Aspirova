// Mirrors backend/api/schemas.py - keep these in sync by hand (Phase 1 has
// no shared schema generation yet).

export interface CompanySummary {
  slug: string;
  name: string;
  domain: string | null;
  logo_url: string | null;
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
}

export interface OpportunityDetail extends OpportunityListItem {
  description_raw: string;
  summary: string | null;
  apply_url: string;
}

export interface FeedResponse {
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
