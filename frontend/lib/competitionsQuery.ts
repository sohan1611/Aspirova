import { getFeed } from "@/lib/api";
import type { FeedResultData } from "@/lib/feedQuery";

// Single source of truth for reading /competitions' query string, for the same
// reason lib/feedQuery.ts exists: the static prerender and the client component
// that takes over on a filtered URL must agree exactly on what the default view
// is, or the default either double-fetches or renders something the prerender
// did not.

export const COMPETITIONS_LIMIT = 20;

// The crawler runs once a day, so the data changes once a day. Freshness comes
// from the crawl's revalidation push; this is the safety net.
export const COMPETITIONS_REVALIDATE = 21600;

export type CompetitionSort = "recent" | "deadline";
export type LocationScope = "abroad" | "domestic" | "both";

export interface CompetitionsRequest {
  page: number;
  sort: CompetitionSort;
  scope: LocationScope | undefined;
  country: string | undefined;
  remote: boolean | undefined;
  canReusePrerendered: boolean;
}

function parseScope(scope: string | null): LocationScope | undefined {
  return scope === "abroad" || scope === "domestic" || scope === "both" ? scope : undefined;
}

function parseRemote(remote: string | null): boolean | undefined {
  if (remote === "true") return true;
  if (remote === "false") return false;
  return undefined;
}

function parseCountry(country: string | null): string | undefined {
  if (!country || !/^[A-Za-z]{2}$/.test(country)) return undefined;
  return country.toUpperCase();
}

export function parseCompetitionsRequest(sp: URLSearchParams): CompetitionsRequest {
  const page = Math.max(1, Number(sp.get("page") ?? "1") || 1);
  // "deadline" is the default sort, so ?sort=deadline is still the default view.
  const sort: CompetitionSort = sp.get("sort") === "recent" ? "recent" : "deadline";
  const scope = parseScope(sp.get("scope"));
  const country = parseCountry(sp.get("country"));
  const remote = parseRemote(sp.get("remote"));

  const canReusePrerendered =
    page === 1 &&
    sort === "deadline" &&
    scope === undefined &&
    country === undefined &&
    remote === undefined;

  return { page, sort, scope, country, remote, canReusePrerendered };
}

export function loadCompetitions(
  request: CompetitionsRequest,
  revalidateSeconds?: number,
): Promise<FeedResultData> {
  return getFeed(
    {
      kind: "competitions",
      scope: request.scope,
      country: request.country,
      remote: request.remote,
      sort: request.sort,
      page: request.page,
      limit: COMPETITIONS_LIMIT,
    },
    revalidateSeconds,
  );
}

// The request the statically prerendered page is built from: no query string.
export function defaultCompetitionsRequest(): CompetitionsRequest {
  return parseCompetitionsRequest(new URLSearchParams());
}

export function competitionsTotalPages(total: number): number {
  return Math.max(1, Math.ceil(total / COMPETITIONS_LIMIT));
}

export function opportunityCountLabel(count: number): string {
  return `${count} ${count === 1 ? "opportunity" : "opportunities"}`;
}
