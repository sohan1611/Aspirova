import type {
  AccountMe,
  AccountUpdate,
  BookmarkStage,
  BugReportRequest,
  BugReportResponse,
  CompanyListItem,
  CompanyPage,
  CopilotResponse,
  Facets,
  FeedResponse,
  MatchItem,
  NotificationsResponse,
  OpportunityDetail,
  OpportunityListItem,
  PlanPublic,
  ProgrammeDetail,
  ProgrammeListResponse,
  ReferralClaimResult,
  ReferralMe,
  SavedSearchCreate,
  SavedSearchItem,
  SavedOpportunityItem,
  SearchResponse,
  StatsResponse,
  TrendingResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ProFeatureRequiredError extends Error {
  readonly status = 403;

  constructor() {
    super("Resume Match requires a Pro plan.");
    this.name = "ProFeatureRequiredError";
  }
}

export function isProFeatureRequiredError(
  error: unknown,
): error is ProFeatureRequiredError {
  return error instanceof ProFeatureRequiredError;
}

export class RateLimitedError extends Error {
  readonly status = 429;

  constructor() {
    super("Daily Copilot limit reached.");
    this.name = "RateLimitedError";
  }
}

export function isRateLimitedError(error: unknown): error is RateLimitedError {
  return error instanceof RateLimitedError;
}

export class CheckoutConflictError extends Error {
  readonly status = 409;

  constructor(detail: string) {
    super(detail);
    this.name = "CheckoutConflictError";
  }
}

export function isCheckoutConflictError(error: unknown): error is CheckoutConflictError {
  return error instanceof CheckoutConflictError;
}

function throwResumeApiError(res: Response, action: string): never {
  if (res.status === 403) throw new ProFeatureRequiredError();
  throw new Error(`${action}: ${res.status}`);
}

export interface FeedParams {
  category?: "internship" | "job";
  kind?: "roles" | "competitions";
  source?: "direct" | "unstop" | "remoteok" | "devpost";
  experience?: "early";
  remote?: boolean;
  location?: string | string[];
  company?: string | string[];
  top?: number;
  scope?: "abroad" | "domestic" | "both";
  country?: string;
  remote_abroad?: boolean;
  sort?: "student" | "recent" | "deadline";
  page?: number;
  limit?: number;
}

export interface ForYouParams {
  terms?: string[];
  skills?: string[];
  fields?: string[];
  categories?: string[];
  country?: string;
  scope?: "abroad" | "domestic" | "both";
  page?: number;
  limit?: number;
}

export interface ProgrammeParams {
  category?: string;
  country?: string;
  status?: "expected" | "announced" | "open" | "closed";
  q?: string;
  divisions?: string[];
  page?: number;
  limit?: number;
}

type SearchFilterParams = Pick<
  FeedParams,
  | "category"
  | "kind"
  | "source"
  | "experience"
  | "remote"
  | "location"
  | "company"
  | "top"
  | "scope"
  | "country"
  | "remote_abroad"
>;

function appendRepeatedParam(
  search: URLSearchParams,
  key: "company" | "location",
  value: string | string[] | undefined,
) {
  const values = Array.isArray(value) ? value : value ? [value] : [];
  for (const item of values) {
    const nextValue = item.trim();
    if (nextValue) search.append(key, nextValue);
  }
}

export async function getFeed(params: FeedParams = {}): Promise<FeedResponse> {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.kind) search.set("kind", params.kind);
  if (params.source) search.set("source", params.source);
  if (params.experience) search.set("experience", params.experience);
  if (params.remote !== undefined) search.set("remote", String(params.remote));
  appendRepeatedParam(search, "location", params.location);
  appendRepeatedParam(search, "company", params.company);
  if (params.top) search.set("top", String(params.top));
  if (params.scope) search.set("scope", params.scope);
  if (params.country) search.set("country", params.country);
  if (params.remote_abroad) search.set("remote_abroad", "true");
  if (params.sort === "recent" || params.sort === "deadline") {
    search.set("sort", params.sort);
  }
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));

  const res = await fetch(`${API_URL}/feed?${search.toString()}`, { next: { revalidate: 300 } });
  if (!res.ok) throw new Error(`Failed to load feed: ${res.status}`);
  return res.json();
}

export async function pingOpportunityView(slug: string): Promise<void> {
  try {
    await fetch(`${API_URL}/opportunities/${encodeURIComponent(slug)}/view`, {
      method: "POST",
    });
  } catch {
    // View tracking must never affect the detail page.
  }
}

export async function getTrending(limit?: number): Promise<TrendingResponse> {
  try {
    const search = limit === undefined ? "" : `?limit=${encodeURIComponent(String(limit))}`;
    const res = await fetch(`${API_URL}/trending${search}`, { next: { revalidate: 600 } });
    if (!res.ok) return { items: [] };
    return res.json();
  } catch {
    return { items: [] };
  }
}

export async function getForYou(params: ForYouParams = {}): Promise<FeedResponse> {
  const search = new URLSearchParams();
  if (params.terms?.length) {
    search.set("terms", params.terms.join(","));
  } else if (params.fields?.length) {
    search.set("fields", params.fields.join(","));
  }
  if (params.skills?.length) {
    search.set("skills", params.skills.join(","));
  }
  if (params.categories?.length) search.set("categories", params.categories.join(","));
  if (params.country) search.set("country", params.country);
  if (params.scope) search.set("scope", params.scope);
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));

  const res = await fetch(`${API_URL}/for-you?${search.toString()}`, {
    next: { revalidate: 300 },
  });
  if (!res.ok) throw new Error(`Failed to load personalized feed: ${res.status}`);
  return res.json();
}

export async function getStats(): Promise<StatsResponse> {
  const res = await fetch(`${API_URL}/stats`, { next: { revalidate: 300 } });
  if (!res.ok) throw new Error(`Failed to load stats: ${res.status}`);
  return res.json();
}

export async function getFacets(): Promise<Facets> {
  const res = await fetch(`${API_URL}/facets`, { next: { revalidate: 3600 } });
  if (!res.ok) throw new Error(`Failed to load facets: ${res.status}`);
  return res.json();
}

export async function searchOpportunities(
  q: string,
  filters: SearchFilterParams = {},
  page = 1,
  limit = 20,
): Promise<SearchResponse> {
  const search = new URLSearchParams({ q, page: String(page), limit: String(limit) });
  if (filters.category) search.set("category", filters.category);
  if (filters.kind) search.set("kind", filters.kind);
  if (filters.source) search.set("source", filters.source);
  if (filters.experience) search.set("experience", filters.experience);
  if (filters.remote !== undefined) search.set("remote", String(filters.remote));
  appendRepeatedParam(search, "location", filters.location);
  appendRepeatedParam(search, "company", filters.company);
  if (filters.top) search.set("top", String(filters.top));
  if (filters.scope) search.set("scope", filters.scope);
  if (filters.country) search.set("country", filters.country);
  if (filters.remote_abroad) search.set("remote_abroad", "true");
  const res = await fetch(`${API_URL}/search?${search.toString()}`, {
    next: { revalidate: 300 },
  });
  if (!res.ok) throw new Error(`Failed to search: ${res.status}`);
  return res.json();
}

// This fetch revalidate caps its route's ISR window; lowering it silently shortens page cache lifetime.
export async function getOpportunity(slug: string): Promise<OpportunityDetail | null> {
  const res = await fetch(`${API_URL}/opportunity/${encodeURIComponent(slug)}`, {
    next: { revalidate: 604800 },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load opportunity: ${res.status}`);
  return res.json();
}

export async function getProgrammes(
  params: ProgrammeParams = {},
): Promise<ProgrammeListResponse> {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.country) search.set("country", params.country);
  if (params.status) search.set("status", params.status);
  if (params.q) search.set("q", params.q);
  if (params.divisions?.length) search.set("divisions", params.divisions.join(","));
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));

  const query = search.toString();
  const res = await fetch(`${API_URL}/programmes${query ? `?${query}` : ""}`, {
    next: { revalidate: 21600 },
  });
  if (!res.ok) throw new Error(`Failed to load programmes: ${res.status}`);
  return res.json();
}

// This fetch revalidate caps its route's ISR window; lowering it silently shortens page cache lifetime.
export async function getProgramme(slug: string): Promise<ProgrammeDetail | null> {
  const res = await fetch(`${API_URL}/programme/${encodeURIComponent(slug)}`, {
    next: { revalidate: 604800 },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load programme: ${res.status}`);
  return res.json();
}

// This fetch revalidate caps its route's ISR window; lowering it silently shortens page cache lifetime.
export async function getSimilarOpportunities(
  slug: string,
  limit = 6,
): Promise<OpportunityListItem[]> {
  try {
    const search = new URLSearchParams({ limit: String(limit) });
    const res = await fetch(
      `${API_URL}/opportunity/${encodeURIComponent(slug)}/similar?${search.toString()}`,
      { next: { revalidate: 604800 } },
    );
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

// This fetch revalidate caps its route's ISR window; lowering it silently shortens page cache lifetime.
export async function getCompanyPage(
  slug: string,
  page = 1,
  limit = 20,
): Promise<CompanyPage | null> {
  const search = new URLSearchParams({ page: String(page), limit: String(limit) });
  const res = await fetch(`${API_URL}/company/${encodeURIComponent(slug)}?${search.toString()}`, {
    next: { revalidate: 604800 },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load company: ${res.status}`);
  return res.json();
}

export async function getCompanies(): Promise<CompanyListItem[]> {
  const res = await fetch(`${API_URL}/companies`, { next: { revalidate: 3600 } });
  if (!res.ok) throw new Error(`Failed to load companies: ${res.status}`);
  return res.json();
}

export async function addBookmark(slug: string, accessToken: string): Promise<void> {
  const res = await fetch(`${API_URL}/bookmarks/${encodeURIComponent(slug)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error(`Failed to bookmark: ${res.status}`);
}

export async function removeBookmark(slug: string, accessToken: string): Promise<void> {
  const res = await fetch(`${API_URL}/bookmarks/${encodeURIComponent(slug)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error(`Failed to remove bookmark: ${res.status}`);
}

export async function getBookmarks(accessToken: string): Promise<SavedOpportunityItem[]> {
  const res = await fetch(`${API_URL}/bookmarks`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to load bookmarks: ${res.status}`);
  return res.json();
}

export async function createSavedSearch(
  accessToken: string,
  payload: SavedSearchCreate,
): Promise<SavedSearchItem> {
  const res = await fetch(`${API_URL}/saved-searches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to save search: ${res.status}`);
  return res.json();
}

export async function getSavedSearches(accessToken: string): Promise<SavedSearchItem[]> {
  const res = await fetch(`${API_URL}/saved-searches`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to load saved searches: ${res.status}`);
  return res.json();
}

export async function deleteSavedSearch(accessToken: string, id: number): Promise<void> {
  const res = await fetch(`${API_URL}/saved-searches/${encodeURIComponent(String(id))}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error(`Failed to delete saved search: ${res.status}`);
}

export async function setSavedSearchAlerts(
  accessToken: string,
  id: number,
  enabled: boolean,
): Promise<SavedSearchItem> {
  const res = await fetch(`${API_URL}/saved-searches/${encodeURIComponent(String(id))}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ alerts_enabled: enabled }),
  });
  if (!res.ok) throw new Error(`Failed to update saved search alerts: ${res.status}`);
  return res.json();
}

export async function getNotifications(accessToken: string): Promise<NotificationsResponse> {
  const res = await fetch(`${API_URL}/notifications`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to load notifications: ${res.status}`);
  return res.json();
}

export async function getUnreadCount(accessToken: string): Promise<{ unread: number }> {
  const res = await fetch(`${API_URL}/notifications/unread-count`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to load unread notifications: ${res.status}`);
  return res.json();
}

export async function markNotificationsRead(accessToken: string): Promise<{ unread: number }> {
  const res = await fetch(`${API_URL}/notifications/read`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error(`Failed to mark notifications as read: ${res.status}`);
  return res.json();
}

export async function updateBookmarkStatus(
  slug: string,
  status: BookmarkStage,
  accessToken: string,
): Promise<void> {
  const res = await fetch(`${API_URL}/bookmarks/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(`Failed to update bookmark status: ${res.status}`);
}

export async function uploadResume(
  resumeText: string,
  accessToken: string,
): Promise<{ version: number }> {
  const res = await fetch(`${API_URL}/resume`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ resume_text: resumeText }),
  });
  if (!res.ok) throwResumeApiError(res, "Failed to upload resume");
  return res.json();
}

export async function getResumeMatches(
  accessToken: string,
  limit = 20,
): Promise<MatchItem[]> {
  const search = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_URL}/resume/matches?${search.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throwResumeApiError(res, "Failed to load resume matches");
  return res.json();
}

export async function getReferralMe(accessToken: string): Promise<ReferralMe> {
  const res = await fetch(`${API_URL}/referral/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to load referral profile: ${res.status}`);
  return res.json();
}

export async function claimReferral(
  code: string,
  accessToken: string,
): Promise<ReferralClaimResult> {
  const res = await fetch(`${API_URL}/referral/claim`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error(`Failed to claim referral: ${res.status}`);
  return res.json();
}

export async function askCopilot(
  message: string,
  accessToken: string,
): Promise<CopilotResponse> {
  const res = await fetch(`${API_URL}/copilot`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
  });

  if (res.status === 403) throw new ProFeatureRequiredError();
  if (res.status === 429) throw new RateLimitedError();
  if (!res.ok) throw new Error(`Failed to ask Copilot: ${res.status}`);
  return res.json();
}

export async function getPlans(): Promise<PlanPublic[]> {
  const res = await fetch(`${API_URL}/plans`, { next: { revalidate: 300 } });
  if (!res.ok) throw new Error(`Failed to load plans: ${res.status}`);
  return res.json();
}

export async function createCheckout(
  planKey: string,
  accessToken: string,
): Promise<{ razorpay_subscription_id: string; razorpay_key_id: string }> {
  const res = await fetch(`${API_URL}/payments/checkout/${encodeURIComponent(planKey)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (res.status === 409) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : "Please cancel your current plan before switching plans.";
    throw new CheckoutConflictError(detail);
  }
  if (!res.ok) throw new Error(`Failed to start checkout: ${res.status}`);
  return res.json();
}

export async function getAccount(accessToken: string): Promise<AccountMe> {
  const res = await fetch(`${API_URL}/account/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to load account: ${res.status}`);
  return res.json();
}

export async function updateAccount(
  accessToken: string,
  patch: AccountUpdate,
): Promise<AccountMe> {
  const res = await fetch(`${API_URL}/account/me`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`Failed to update account: ${res.status}`);
  return res.json();
}

export async function cancelSubscription(accessToken: string): Promise<void> {
  const res = await fetch(`${API_URL}/subscription/cancel`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error(`Failed to cancel subscription: ${res.status}`);
}

export async function joinWaitlist(email: string): Promise<void> {
  const res = await fetch(`${API_URL}/waitlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error(`Failed to join waitlist: ${res.status}`);
}

export async function submitBugReport(
  payload: BugReportRequest,
  accessToken?: string,
): Promise<BugReportResponse> {
  const res = await fetch(`${API_URL}/reports`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to submit report: ${res.status}`);
  return res.json();
}
