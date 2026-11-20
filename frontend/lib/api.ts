import type { HomeDesk } from "./home";
import { fetchListing, type ListingSnapshot } from "./listingFetch";
import { appendRoleSignalParams, type RoleSignalParams } from "./roleSignalQuery";
import type {
  AccountMe,
  AccountUpdate,
  BookmarkStage,
  BookmarkUpdate,
  BugReportRequest,
  BugReportResponse,
  ReportStatus,
  CompanyListItem,
  CompanyPage,
  CompanySummary,
  CopilotResponse,
  DreamCompanyItem,
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
  SavedSearchParams,
  SavedOpportunityItem,
  SearchResponse,
  SearchRelatedResponse,
  StatsResponse,
  TrendingResponse,
  DigestPreview,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class AccountDeletionError extends Error {
  constructor(readonly detail: string) {
    super(detail);
  }
}

export async function deleteAccount(accessToken: string): Promise<void> {
  const response = await fetch(`${API_URL}/account/delete`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: "DELETE" }),
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new AccountDeletionError(typeof body.detail === "string" ? body.detail : "request_failed");
  }
}

export type EmailSampleKind = "company-alert" | "weekly-report";

export interface EmailSample {
  subject: string;
  html: string;
}

export async function getEmailSample(kind: EmailSampleKind): Promise<EmailSample> {
  const res = await fetch(`${API_URL}/email-samples/${kind}`);
  if (!res.ok) throw new Error(`Failed to load email example: ${res.status}`);
  return res.json();
}

export async function getExternalCompanyLogos(): Promise<Record<string, CompanySummary>> {
  const res = await fetch(`${API_URL}/companies/external`);
  if (!res.ok) throw new Error(`Failed to load external company logos: ${res.status}`);
  return res.json();
}

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

export class SessionExpiredError extends Error {
  readonly status: number;

  constructor(status: number) {
    super("Your session has expired. Sign in again to continue.");
    this.name = "SessionExpiredError";
    this.status = status;
  }
}

export function isSessionExpiredError(error: unknown): error is SessionExpiredError {
  return error instanceof SessionExpiredError;
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

export interface FeedParams extends RoleSignalParams {
  deadline_confidence?: "explicit";
  category?: "internship" | "job" | "hackathon" | "competition" | "scholarship";
  kind?: "roles" | "competitions";
  source?: "direct" | "unstop" | "remoteok" | "devpost";
  experience?: "early" | "new_grad";
  remote?: boolean;
  location?: string | string[];
  company?: string | string[];
  top?: number;
  scope?: "abroad" | "domestic" | "both";
  country?: string;
  prefer_country?: string;
  prefer_logos?: boolean;
  remote_abroad?: boolean;
  comp_type?: string | string[];
  registration?: string;
  deadline_within?: number;
  organiser_type?: string | string[];
  mode?: string | string[];
  prize_min?: number;
  status?: "open" | "closed";
  sort?: "student" | "recent" | "deadline" | "prize" | "pay";
  students?: boolean;
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
  category?: string | string[];
  country?: string;
  status?: string | string[];
  field?: string | string[];
  organiser?: string | string[];
  institution_type?: string | string[];
  q?: string;
  divisions?: string[];
  page?: number;
  limit?: number;
}

type SearchFilterParams = Pick<
  FeedParams,
  | keyof RoleSignalParams
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
  | "comp_type"
  | "registration"
  | "deadline_within"
  | "organiser_type"
  | "mode"
  | "prize_min"
  | "status"
  | "sort"
  | "students"
>;

function appendRepeatedParam(
  search: URLSearchParams,
  key: "company" | "location" | "comp_type" | "organiser_type" | "mode",
  value: string | string[] | undefined,
) {
  const values = Array.isArray(value) ? value : value ? [value] : [];
  for (const item of values) {
    const nextValue = item.trim();
    if (nextValue) search.append(key, nextValue);
  }
}

function appendStringParams(
  search: URLSearchParams,
  key: string,
  value: string | string[] | undefined,
) {
  const values = Array.isArray(value) ? value : value ? [value] : [];
  for (const item of values) {
    const nextValue = item.trim();
    if (nextValue) search.append(key, nextValue);
  }
}

// `revalidateSeconds` caps the calling route's ISR window, exactly as noted on
// getOpportunity below: a route that declares `revalidate = 21600` still
// regenerates every 300s if its fetch says 300. The ISR landing pages pass their
// own window so the page-level setting is not silently overridden.
export async function getFeed(
  params: FeedParams = {},
  revalidateSeconds = 300,
): Promise<ListingSnapshot<FeedResponse>> {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.deadline_confidence) search.set("deadline_confidence", params.deadline_confidence);
  if (params.kind) search.set("kind", params.kind);
  if (params.source) search.set("source", params.source);
  if (params.experience) search.set("experience", params.experience);
  appendRoleSignalParams(search, params);
  if (params.remote !== undefined) search.set("remote", String(params.remote));
  appendRepeatedParam(search, "location", params.location);
  appendRepeatedParam(search, "company", params.company);
  if (params.top) search.set("top", String(params.top));
  if (params.scope) search.set("scope", params.scope);
  if (params.country) search.set("country", params.country);
  if (params.prefer_country) search.set("prefer_country", params.prefer_country);
  if (params.prefer_logos) search.set("prefer_logos", "true");
  if (params.remote_abroad) search.set("remote_abroad", "true");
  appendRepeatedParam(search, "comp_type", params.comp_type);
  if (params.registration) search.set("registration", params.registration);
  if (params.deadline_within !== undefined) {
    search.set("deadline_within", String(params.deadline_within));
  }
  appendRepeatedParam(search, "organiser_type", params.organiser_type);
  appendRepeatedParam(search, "mode", params.mode);
  if (params.status) search.set("status", params.status);
  if (params.prize_min !== undefined) search.set("prize_min", String(params.prize_min));
  if (
    params.sort === "recent" ||
    params.sort === "deadline" ||
    params.sort === "prize" ||
    params.sort === "pay" ||
    params.sort === "student"
  ) {
    search.set("sort", params.sort);
  }
  if (params.students === true) search.set("students", "true");
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));

  return fetchListing<FeedResponse>(`${API_URL}/feed?${search.toString()}`, revalidateSeconds, "page");
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

// revalidateSeconds caps the calling route's ISR window - see getFeed above.
export async function getTrending(
  limit?: number,
  revalidateSeconds = 600,
  preferLogos = false,
): Promise<TrendingResponse> {
  const search = new URLSearchParams();
  if (limit !== undefined) search.set("limit", String(limit));
  if (preferLogos) search.set("prefer_logos", "true");
  const query = search.toString();
  const data = await fetchListing<TrendingResponse>(`${API_URL}/trending${query ? `?${query}` : ""}`, revalidateSeconds, "object");
  if (!Array.isArray(data.items)) throw new Error("Invalid trending response");
  return data;
}

export async function getForYou(params: ForYouParams = {}): Promise<ListingSnapshot<FeedResponse>> {
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

  return fetchListing<FeedResponse>(`${API_URL}/for-you?${search.toString()}`, 300, "page");
}
// revalidateSeconds caps the calling route's ISR window - see getFeed above.
export async function getStats(revalidateSeconds = 300): Promise<ListingSnapshot<StatsResponse>> {
  return fetchListing<StatsResponse>(`${API_URL}/stats`, revalidateSeconds, "object");
}
export async function getFacets(
  params: Pick<FeedParams, "kind"> & {
    category?: FeedParams["category"] | string | string[];
    source?: "opportunities" | "programmes";
  } = {},
): Promise<ListingSnapshot<Facets>> {
  const search = new URLSearchParams();
  if (params.kind) search.set("kind", params.kind);
  appendStringParams(search, "category", params.category);
  if (params.source) search.set("source", params.source);
  const query = search.toString();
  return fetchListing<Facets>(`${API_URL}/facets${query ? "?" + query : ""}`, 3600, "object");
}
export async function searchOpportunities(
  q: string,
  filters: SearchFilterParams = {},
  page = 1,
  limit = 20,
): Promise<ListingSnapshot<SearchResponse>> {
  const search = new URLSearchParams({ q, page: String(page), limit: String(limit) });
  if (filters.category) search.set("category", filters.category);
  if (filters.kind) search.set("kind", filters.kind);
  if (filters.source) search.set("source", filters.source);
  if (filters.experience) search.set("experience", filters.experience);
  appendRoleSignalParams(search, filters);
  if (filters.remote !== undefined) search.set("remote", String(filters.remote));
  appendRepeatedParam(search, "location", filters.location);
  appendRepeatedParam(search, "company", filters.company);
  if (filters.top) search.set("top", String(filters.top));
  if (filters.scope) search.set("scope", filters.scope);
  if (filters.country) search.set("country", filters.country);
  if (filters.remote_abroad) search.set("remote_abroad", "true");
  appendRepeatedParam(search, "comp_type", filters.comp_type);
  if (filters.registration) search.set("registration", filters.registration);
  if (filters.deadline_within !== undefined) {
    search.set("deadline_within", String(filters.deadline_within));
  }
  appendRepeatedParam(search, "organiser_type", filters.organiser_type);
  appendRepeatedParam(search, "mode", filters.mode);
  if (filters.status) search.set("status", filters.status);
  if (filters.prize_min !== undefined) search.set("prize_min", String(filters.prize_min));
  if (filters.sort) search.set("sort", filters.sort);
  if (filters.students === true) search.set("students", "true");
  // Search is query-specific and browser-driven. These query modules are used
  // by client results components; static pages never take the q branch because
  // they do not read searchParams. Server fetch-cache options are meaningless
  // in the browser, so fetchListing gets a zero server-cache window here.
  // Removing next: { revalidate } was tried during the earlier search bug and
  // did not fix it: the lost component state is documented in listingStore.ts.
  return fetchListing<SearchResponse>(`${API_URL}/search?${search.toString()}`, 0, "page");
}
// This fetch revalidate caps its route's ISR window; lowering it silently shortens page cache lifetime.
export async function getOpportunity(
  slug: string,
  revalidateSeconds = 604800,
): Promise<OpportunityDetail | null> {
  const res = await fetch(`${API_URL}/opportunity/${encodeURIComponent(slug)}`, {
    next: { revalidate: revalidateSeconds },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load opportunity: ${res.status}`);
  return res.json();
}

export async function getProgrammes(
  params: ProgrammeParams = {},
  revalidateSeconds = 21600,
): Promise<ListingSnapshot<ProgrammeListResponse>> {
  const search = new URLSearchParams();
  appendStringParams(search, "category", params.category);
  if (params.country) search.set("country", params.country);
  appendStringParams(search, "status", params.status);
  appendStringParams(search, "field", params.field);
  appendStringParams(search, "organiser", params.organiser);
  appendStringParams(search, "institution_type", params.institution_type);
  if (params.q) search.set("q", params.q);
  if (params.divisions?.length) search.set("divisions", params.divisions.join(","));
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));

  const query = search.toString();
  return fetchListing<ProgrammeListResponse>(`${API_URL}/programmes${query ? "?" + query : ""}`, revalidateSeconds, "page");
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
  const search = new URLSearchParams({ limit: String(limit) });
  return fetchListing<OpportunityListItem[]>(`${API_URL}/opportunity/${encodeURIComponent(slug)}/similar?${search}`, 604800, "array");
}

// This fetch revalidate caps its route's ISR window; lowering it silently shortens page cache lifetime.
export async function getCompanyPage(
  slug: string,
  page = 1,
  limit = 20,
): Promise<ListingSnapshot<CompanyPage> | null> {
  const search = new URLSearchParams({ page: String(page), limit: String(limit) });
  return fetchListing<CompanyPage | null>(`${API_URL}/company/${encodeURIComponent(slug)}?${search}`, 604800, "company");
}

export async function getCompanies(): Promise<ListingSnapshot<CompanyListItem[]>> {
  return fetchListing<CompanyListItem[]>(`${API_URL}/companies`, 86400, "array");
}
export async function getTopCompanies(limit = 12, preferLogos = false): Promise<ListingSnapshot<CompanyListItem[]>> {
  const search = new URLSearchParams({ limit: String(limit) });
  if (preferLogos) search.set("prefer_logos", "true");
  return fetchListing<CompanyListItem[]>(`${API_URL}/companies/top?${search.toString()}`, 21600, "array");
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
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`Failed to load bookmarks: ${res.status}`);
  const items: SavedOpportunityItem[] = await res.json();
  if (!Array.isArray(items)) throw new Error("Invalid bookmarks response");
  return items;
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
  if (!res.ok) {
    if (res.status === 409) throw new Error("Saved search limit of 25 reached");
    throw new Error("We couldn't save this search. Please try again.");
  }
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

export async function updateSavedSearch(
  accessToken: string,
  id: number,
  patch: { name?: string | null; params?: SavedSearchParams; alerts_enabled?: boolean },
): Promise<SavedSearchItem> {
  const res = await fetch(`${API_URL}/saved-searches/${encodeURIComponent(String(id))}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("We couldn't update this search. Please try again.");
  return res.json();
}

export async function setSavedSearchAlerts(
  accessToken: string,
  id: number,
  enabled: boolean,
): Promise<SavedSearchItem> {
  return updateSavedSearch(accessToken, id, { alerts_enabled: enabled });
}

export async function getNotifications(accessToken: string): Promise<NotificationsResponse> {
  const res = await fetch(`${API_URL}/notifications`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (res.status === 401 || res.status === 403) throw new SessionExpiredError(res.status);
  if (!res.ok) throw new Error(`Failed to load notifications: ${res.status}`);
  return res.json();
}

export async function getUnreadCount(accessToken: string): Promise<{ unread: number }> {
  const res = await fetch(`${API_URL}/notifications/unread-count`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (res.status === 401 || res.status === 403) throw new SessionExpiredError(res.status);
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
  return updateBookmark(slug, { status }, accessToken);
}

export async function updateBookmark(
  slug: string,
  update: BookmarkUpdate,
  accessToken: string,
): Promise<void> {
  const res = await fetch(`${API_URL}/bookmarks/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(update),
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

export async function getAccount(accessToken: string, signal?: AbortSignal): Promise<AccountMe> {
  const res = await fetch(`${API_URL}/account/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`Failed to load account: ${res.status}`);
  return res.json();
}

export class DigestPreviewRateLimitError extends Error {}

export async function getDigestPreview(accessToken: string): Promise<DigestPreview> {
  const res = await fetch(`${API_URL}/account/digest-preview`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (res.status === 429) throw new DigestPreviewRateLimitError("Too many previews");
  if (!res.ok) throw new Error(`Failed to load digest preview: ${res.status}`);
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

export async function getReportStatus(reference: string): Promise<ReportStatus> {
  const response = await fetch(
    `${API_URL}/reports/status/${encodeURIComponent(reference.trim().toUpperCase())}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(response.status === 404
    ? "Report not found. Check your receipt code."
    : response.status === 429 ? "Too many lookups. Please try again in a minute."
    : "We couldn't check your report. Please try again.");
  return response.json();
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

export async function pingOpportunityAction(slug: string, action: "apply" | "gate"): Promise<void> {
  try {
    await fetch(
      `${API_URL}/opportunities/${encodeURIComponent(slug)}/actions/${action}`,
      { method: "POST", keepalive: true },
    );
  } catch {
    // The visitor may already be leaving the page.
  }
}

export async function getDreamCompanies(accessToken: string): Promise<DreamCompanyItem[]> {
  const res = await fetch(`${API_URL}/dream-companies`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error("Couldn't load followed companies");
  const items: DreamCompanyItem[] = await res.json();
  if (!Array.isArray(items)) throw new Error("Invalid followed companies response");
  return items;
}

export class FollowLimitError extends Error {
  constructor(readonly detail: string) {
    super(detail);
    this.name = "FollowLimitError";
  }
}

export function companyAlertLimitMessage(error: FollowLimitError): string {
  const limit = error.detail.match(/\((\d+)\)/)?.[1];
  return limit === "1"
    ? "Free accounts can follow 1 company. Remove one in settings, or see plans."
    : `Your plan's company follow limit${limit ? ` of ${limit}` : ""} is reached. Remove one in settings, or see plans.`;
}

export async function saveCompanyAlerts(slugs: string[], roles: string[], accessToken: string): Promise<void> {
  const res = await fetch(`${API_URL}/dream-companies`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ company_slugs: slugs, roles }),
  });
  if (res.status === 403) {
    const payload = await res.json();
    throw new FollowLimitError(payload.detail);
  }
  if (!res.ok) throw new Error("Couldn't save company alerts");
}

export async function searchCompanies(query: string, signal?: AbortSignal): Promise<CompanyListItem[]> {
  const q = query.trim();
  if (q.length < 2) return [];
  const search = new URLSearchParams({ q, limit: "20" });
  const timeout = AbortSignal.timeout(20_000);
  const res = await fetch(`${API_URL}/companies/search?${search.toString()}`, { signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!res.ok) throw new Error("Couldn't search companies");
  const companies: CompanyListItem[] = await res.json();
  if (!Array.isArray(companies)) throw new Error("Invalid company search response");
  return companies;
}

export async function addDreamCompany(slug: string, accessToken: string): Promise<void> {
  const res = await fetch(`${API_URL}/dream-companies/${encodeURIComponent(slug)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (res.status === 403) {
    const payload = await res.json();
    throw new FollowLimitError(payload.detail);
  }
  if (!res.ok) throw new Error("Couldn't follow this company");
}

export async function removeDreamCompany(slug: string, accessToken: string): Promise<void> {
  const res = await fetch(`${API_URL}/dream-companies/${encodeURIComponent(slug)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error("Couldn't unfollow this company");
}

export async function exportAccountData(accessToken: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_URL}/account/export`, {
    headers: { Authorization: "Bearer " + accessToken },
    cache: "no-store",
  });
  if (!res.ok) throw new Error("We couldn't download your data. Please try again.");
  return res.json();
}

export async function getHomeDesk(accessToken: string, signal?: AbortSignal): Promise<HomeDesk> {
  const timeout = AbortSignal.timeout(20_000);
  const response = await fetch(`${API_URL}/home/desk`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  if (!response.ok) throw new Error("Couldn't load your action desk");
  const data = await response.json();
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid action desk response");
  return data;
}

/** Public client enhancement: no ISR cache or authentication. */
export async function getSearchRelated(q: string, signal?: AbortSignal): Promise<SearchRelatedResponse> {
  const timeout = AbortSignal.timeout(8_000);
  const response = await fetch(
    `${API_URL}/search/related?${new URLSearchParams({ q: q.trim() })}`,
    { cache: "no-store", signal: signal ? AbortSignal.any([signal, timeout]) : timeout },
  );
  if (!response.ok) throw new Error(`Couldn't load related search: ${response.status}`);
  const data: SearchRelatedResponse = await response.json();
  if (!data || !Array.isArray(data.programmes?.items) || !Array.isArray(data.companies?.items)) {
    throw new Error("Invalid related search response");
  }
  return data;
}
