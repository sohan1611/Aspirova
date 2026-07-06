import type {
  CopilotResponse,
  FeedResponse,
  MatchItem,
  OpportunityDetail,
  OpportunityListItem,
  PlanPublic,
  SearchResponse,
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

function throwResumeApiError(res: Response, action: string): never {
  if (res.status === 403) throw new ProFeatureRequiredError();
  throw new Error(`${action}: ${res.status}`);
}

export interface FeedParams {
  category?: "internship" | "job";
  remote?: boolean;
  sort?: "recent" | "deadline";
  page?: number;
  limit?: number;
}

export async function getFeed(params: FeedParams = {}): Promise<FeedResponse> {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.remote !== undefined) search.set("remote", String(params.remote));
  if (params.sort) search.set("sort", params.sort);
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));

  const res = await fetch(`${API_URL}/feed?${search.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load feed: ${res.status}`);
  return res.json();
}

export async function searchOpportunities(
  q: string,
  page = 1,
  limit = 20,
): Promise<SearchResponse> {
  const search = new URLSearchParams({ q, page: String(page), limit: String(limit) });
  const res = await fetch(`${API_URL}/search?${search.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to search: ${res.status}`);
  return res.json();
}

export async function getOpportunity(slug: string): Promise<OpportunityDetail | null> {
  const res = await fetch(`${API_URL}/opportunity/${encodeURIComponent(slug)}`, {
    next: { revalidate: 60 },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load opportunity: ${res.status}`);
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

export async function getBookmarks(accessToken: string): Promise<OpportunityListItem[]> {
  const res = await fetch(`${API_URL}/bookmarks`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Failed to load bookmarks: ${res.status}`);
  return res.json();
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

export async function joinWaitlist(email: string): Promise<void> {
  const res = await fetch(`${API_URL}/waitlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error(`Failed to join waitlist: ${res.status}`);
}
