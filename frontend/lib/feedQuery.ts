import { type FeedParams, getFeed, getForYou, searchOpportunities } from "@/lib/api";
import type { OpportunityListItem } from "@/lib/types";

// The three sources this page can draw from return different envelopes -
// SearchResponse has no page/limit - so this is the intersection the feed
// actually renders from. Page and limit come from the parsed request, which is
// the authority for them anyway.
export interface FeedResultData {
  items: OpportunityListItem[];
  total: number;
}

// Single source of truth for reading the homepage's query string. The static
// server render and the client component that takes over on a filtered URL MUST
// agree byte-for-byte on what "the clean default feed" is - if they disagree the
// default view either double-fetches or renders something the prerender did not.
// Both call parseFeedRequest, so there is only one implementation to disagree with.

export const DEFAULT_COLS = 3;
export const DEFAULT_ROWS = 10;

export interface FeedRequest {
  q: string | undefined;
  page: number;
  cols: number;
  rows: number;
  limit: number;
  sort: "student" | "recent" | "deadline";
  kind: "roles" | "competitions" | undefined;
  filters: FeedParams;
  forYouFields: string[] | undefined;
  forYouTerms: string[] | undefined;
  forYouSkills: string[] | undefined;
  isForYou: boolean;
  isCleanDefaultFeed: boolean;
  canReusePrerenderedFeed: boolean;
}

function splitList(value: string | null): string[] | undefined {
  return value
    ?.split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function parseFeedRequest(sp: URLSearchParams): FeedRequest {
  const get = (key: string): string | undefined => sp.get(key) ?? undefined;

  const q = get("q");
  const category = get("category");
  const kindParam = get("kind");
  const sortParam = get("sort");
  const view = get("view");
  const remote = get("remote");
  const topParam = get("top");
  const location = sp.getAll("location");
  const company = sp.getAll("company");

  const page = Math.max(1, Number(get("page") ?? "1") || 1);
  const cols = Math.min(4, Math.max(1, Number(get("cols") ?? String(DEFAULT_COLS)) || DEFAULT_COLS));
  const rows = Math.min(20, Math.max(5, Number(get("rows") ?? String(DEFAULT_ROWS)) || DEFAULT_ROWS));
  const top = topParam ? Number(topParam) : undefined;

  const sort: "student" | "recent" | "deadline" =
    sortParam === "deadline" ? "deadline" : sortParam === "recent" ? "recent" : "student";

  const kind = kindParam
    ? (kindParam as "roles" | "competitions")
    : category
      ? undefined
      : "roles";

  const filters: FeedParams = {
    category: category as "internship" | "job" | undefined,
    kind: kindParam as "roles" | "competitions" | undefined,
    source: get("source") as "direct" | "unstop" | "remoteok" | "devpost" | undefined,
    experience: get("experience") as "early" | undefined,
    remote: remote === "true" ? true : remote === "false" ? false : undefined,
    location: location.length > 0 ? location : undefined,
    company: company.length > 0 ? company : undefined,
    top: top && Number.isFinite(top) && top > 0 ? top : undefined,
    scope: get("scope") as "abroad" | "domestic" | "both" | undefined,
    country: get("country"),
    remote_abroad: get("remote_abroad") === "true" ? true : undefined,
  };

  const forYouFields = splitList(sp.get("fields"));
  const forYouTerms = splitList(sp.get("terms"));
  const forYouSkills = splitList(sp.get("skills"));
  const isForYou = (view === "foryou" || Boolean(forYouSkills?.length)) && !q;

  const hasActiveFilters = Boolean(
    category ||
      kindParam ||
      get("source") ||
      get("experience") ||
      remote !== undefined ||
      location.length > 0 ||
      company.length > 0 ||
      topParam ||
      get("scope") ||
      get("country") ||
      get("remote_abroad") === "true" ||
      sortParam === "recent" ||
      sortParam === "deadline",
  );

  // Unchanged from the original page: this drives whether MostViewed is shown.
  const isCleanDefaultFeed =
    !q &&
    view !== "foryou" &&
    !sp.get("fields") &&
    !sp.get("terms") &&
    !sp.get("skills") &&
    !hasActiveFilters &&
    page === 1;

  // Strictly narrower, and a separate question: may the client reuse the
  // prerendered items instead of fetching? cols/rows change the limit, so
  // ?cols=4 needs 40 rows while the prerender holds 30. Deliberately NOT folded
  // into isCleanDefaultFeed, which would then also hide MostViewed for anyone who
  // merely changed their grid density.
  const canReusePrerenderedFeed =
    isCleanDefaultFeed && cols === DEFAULT_COLS && rows === DEFAULT_ROWS;

  return {
    q,
    page,
    cols,
    rows,
    limit: cols * rows,
    sort,
    kind,
    filters,
    forYouFields,
    forYouTerms,
    forYouSkills,
    isForYou,
    isCleanDefaultFeed,
    canReusePrerenderedFeed,
  };
}

// One implementation of the search / for-you / feed branch, so the static
// prerender and the client takeover cannot drift apart.
// `revalidateSeconds` is only meaningful on the server, where it caps the calling
// route's ISR window; the client passes nothing and gets the normal default.
export function loadFeedData(
  request: FeedRequest,
  revalidateSeconds?: number,
): Promise<FeedResultData> {
  if (request.q) {
    return searchOpportunities(request.q, request.filters, request.page, request.limit);
  }

  if (request.isForYou) {
    return getForYou({
      terms: request.forYouTerms,
      skills: request.forYouSkills,
      fields: request.forYouFields,
      categories: request.filters.category ? [request.filters.category] : undefined,
      country: request.filters.country,
      scope: request.filters.scope,
      page: request.page,
      limit: request.limit,
    });
  }

  return getFeed(
    {
      ...request.filters,
      kind: request.kind,
      sort: request.sort,
      page: request.page,
      limit: request.limit,
    },
    revalidateSeconds,
  );
}

// The request the statically prerendered homepage is built from: no query string
// at all. Anything a visitor's URL adds makes isCleanDefaultFeed false, which is
// the client component's signal to fetch instead of reusing the prerender.
export function defaultFeedRequest(): FeedRequest {
  return parseFeedRequest(new URLSearchParams());
}
