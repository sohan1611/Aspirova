import { getFeed, searchOpportunities } from "@/lib/api";
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

export const COMPETITION_FILTER_PARAM_KEYS = [
  "comp_type",
  "registration",
  "deadline_within",
  "organiser_type",
  "mode",
  "prize_min",
] as const;

export interface CompetitionsRequest {
  q: string | undefined;
  page: number;
  sort: CompetitionSort;
  scope: LocationScope | undefined;
  country: string | undefined;
  remote: boolean | undefined;
  comp_type: string[];
  registration: string | undefined;
  deadline_within: number | undefined;
  organiser_type: string[];
  mode: string[];
  prize_min: number | undefined;
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

function parseRepeated(sp: URLSearchParams, key: string): string[] {
  return Array.from(
    new Set(
      sp
        .getAll(key)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  );
}

function parsePositiveInteger(value: string | null): number | undefined {
  if (!value || !/^\d+$/.test(value.trim())) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : undefined;
}

function parseSingle(value: string | null): string | undefined {
  const nextValue = value?.trim();
  return nextValue || undefined;
}

function hasCompetitionFilterParam(sp: URLSearchParams): boolean {
  return COMPETITION_FILTER_PARAM_KEYS.some((key) =>
    sp
      .getAll(key)
      .some((value) => value.trim() !== ""),
  );
}

export function parseCompetitionsRequest(sp: URLSearchParams): CompetitionsRequest {
  const q = parseSingle(sp.get("q"));
  const page = Math.max(1, Number(sp.get("page") ?? "1") || 1);
  // "deadline" is the default sort, so ?sort=deadline is still the default view.
  const sort: CompetitionSort = sp.get("sort") === "recent" ? "recent" : "deadline";
  const scope = parseScope(sp.get("scope"));
  const country = parseCountry(sp.get("country"));
  const remote = parseRemote(sp.get("remote"));
  const comp_type = parseRepeated(sp, "comp_type");
  const registration = parseSingle(sp.get("registration"));
  const deadline_within = parsePositiveInteger(sp.get("deadline_within"));
  const organiser_type = parseRepeated(sp, "organiser_type");
  const mode = parseRepeated(sp, "mode");
  const prize_min = parsePositiveInteger(sp.get("prize_min"));
  const hasActiveCompetitionFilter = hasCompetitionFilterParam(sp);

  const canReusePrerendered =
    !q &&
    page === 1 &&
    sort === "deadline" &&
    scope === undefined &&
    country === undefined &&
    remote === undefined &&
    !hasActiveCompetitionFilter;

  return {
    q,
    page,
    sort,
    scope,
    country,
    remote,
    comp_type,
    registration,
    deadline_within,
    organiser_type,
    mode,
    prize_min,
    canReusePrerendered,
  };
}

export function loadCompetitions(
  request: CompetitionsRequest,
  revalidateSeconds?: number,
): Promise<FeedResultData> {
  if (request.q) {
    return searchOpportunities(
      request.q,
      {
        kind: "competitions",
        scope: request.scope,
        country: request.country,
        remote: request.remote,
        comp_type: request.comp_type,
        registration: request.registration,
        deadline_within: request.deadline_within,
        organiser_type: request.organiser_type,
        mode: request.mode,
        prize_min: request.prize_min,
        sort: request.sort,
      },
      request.page,
      COMPETITIONS_LIMIT,
    );
  }

  return getFeed(
    {
      kind: "competitions",
      scope: request.scope,
      country: request.country,
      remote: request.remote,
      comp_type: request.comp_type,
      registration: request.registration,
      deadline_within: request.deadline_within,
      organiser_type: request.organiser_type,
      mode: request.mode,
      prize_min: request.prize_min,
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
