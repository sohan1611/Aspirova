import type { FeedResponse, OpportunityDetail, OpportunityListItem, SearchResponse } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
