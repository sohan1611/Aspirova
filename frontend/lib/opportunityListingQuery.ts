import { type FeedParams, getFeed, searchOpportunities } from "@/lib/api";
import { buildPagePath } from "@/lib/pagination";
import type { FacetOption } from "@/lib/types";

export const OPPORTUNITY_LISTING_LIMIT = 20;
export const INDIA_COUNTRY_CODE = "IN";

export type OpportunityListingPath =
  | "/jobs"
  | "/internships"
  | "/remote"
  | "/scholarships"
  | "/competitions";
export type OpportunityListingSort = "student" | "recent" | "deadline";
export type OpportunityListingLocation = "all" | "india" | "abroad" | "remote";

export interface OpportunityListingRequest {
  q: string | undefined;
  page: number;
  limit: number;
  sort: OpportunityListingSort;
  filters: FeedParams;
  canReusePrerendered: boolean;
  usesServerPagination: boolean;
}

export interface OpportunityListingParseOptions {
  basePath: OpportunityListingPath;
  baseQuery: FeedParams;
  defaultSort: OpportunityListingSort;
  initialPage: number;
  limit: number;
}

export interface OpportunityListingCountedFilters {
  locationOptions: FacetOption[];
  sourceOptions: FacetOption[];
  experienceOptions: FacetOption[];
}

interface LocationDefinition {
  value: OpportunityListingLocation;
  label: string;
  params: FeedParams;
}

export const OPPORTUNITY_SOURCE_OPTIONS = [
  { value: "direct", label: "Direct" },
  { value: "unstop", label: "Unstop" },
  { value: "remoteok", label: "RemoteOK" },
  { value: "devpost", label: "Devpost" },
] as const;

export const OPPORTUNITY_EXPERIENCE_OPTIONS = [
  { value: "early", label: "Early career" },
] as const;

const FILTER_PARAM_KEYS = [
  "q",
  "scope",
  "country",
  "remote",
  "company",
  "source",
  "experience",
] as const;

function normalizeSearch(value: string | null): string | undefined {
  const nextValue = value?.trim();
  return nextValue || undefined;
}

export function parseRepeatedParam(sp: URLSearchParams, key: string): string[] {
  return Array.from(
    new Set(
      sp
        .getAll(key)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  );
}

function parsePage(value: string | null, fallback: number): number {
  return Math.max(1, Number(value ?? String(fallback)) || fallback);
}

function parseSort(
  value: string | null,
  defaultSort: OpportunityListingSort,
): OpportunityListingSort {
  if (value === "student" || value === "recent" || value === "deadline") {
    return value;
  }

  return defaultSort;
}

function parseScope(value: string | null): FeedParams["scope"] | undefined {
  if (value === "abroad" || value === "domestic" || value === "both") {
    return value;
  }

  return undefined;
}

export function parseRemoteParam(value: string | null): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

function parseCountry(value: string | null): string | undefined {
  if (!value || !/^[A-Za-z]{2}$/.test(value)) return undefined;
  return value.toUpperCase();
}

function parseSource(value: string | null): FeedParams["source"] | undefined {
  if (value === "direct" || value === "unstop" || value === "remoteok" || value === "devpost") {
    return value;
  }

  return undefined;
}

function parseExperience(value: string | null): FeedParams["experience"] | undefined {
  return value === "early" ? "early" : undefined;
}

function hasRawValue(sp: URLSearchParams, key: string): boolean {
  return sp.getAll(key).some((value) => value.trim() !== "");
}

function hasActiveFilterParam(sp: URLSearchParams, baseQuery: FeedParams): boolean {
  const remoteValue = sp.get("remote");
  const parsedRemote = parseRemoteParam(remoteValue);
  const hasRemoteOverride =
    remoteValue !== null &&
    remoteValue.trim() !== "" &&
    (parsedRemote === undefined || parsedRemote !== baseQuery.remote);

  return (
    hasRawValue(sp, "scope") ||
    hasRawValue(sp, "country") ||
    hasRemoteOverride ||
    hasRawValue(sp, "company") ||
    hasRawValue(sp, "source") ||
    hasRawValue(sp, "experience")
  );
}

export function getOpportunityListingLocation(
  searchParams: URLSearchParams,
  baseQuery: FeedParams,
): OpportunityListingLocation {
  const scope = parseScope(searchParams.get("scope"));
  const country = parseCountry(searchParams.get("country"));

  if (country === INDIA_COUNTRY_CODE && scope === "domestic") return "india";
  if (country === INDIA_COUNTRY_CODE && scope === "abroad") return "abroad";

  const remote = parseRemoteParam(searchParams.get("remote"));
  if (remote === true || (baseQuery.remote === true && remote !== false)) return "remote";

  return "all";
}

export function applyOpportunityListingLocation(
  params: URLSearchParams,
  location: OpportunityListingLocation,
  baseQuery: FeedParams,
) {
  params.delete("scope");
  params.delete("country");
  params.delete("remote");
  params.delete("remote_abroad");

  if (location === "india") {
    params.set("scope", "domestic");
    params.set("country", INDIA_COUNTRY_CODE);
  } else if (location === "abroad") {
    params.set("scope", "abroad");
    params.set("country", INDIA_COUNTRY_CODE);
  } else if (location === "remote" && baseQuery.remote !== true) {
    params.set("remote", "true");
  }
}

export function clearOpportunityListingFilters(params: URLSearchParams) {
  for (const key of FILTER_PARAM_KEYS) {
    if (key === "q") continue;
    params.delete(key);
  }
  params.delete("remote_abroad");
}

export function opportunityListingHref(
  basePath: OpportunityListingPath,
  params: URLSearchParams,
): string {
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}

export function parseOpportunityListingRequest(
  sp: URLSearchParams,
  options: OpportunityListingParseOptions,
): OpportunityListingRequest {
  const q = normalizeSearch(sp.get("q"));
  const sort = parseSort(sp.get("sort"), options.defaultSort);
  const hasActiveFilters = hasActiveFilterParam(sp, options.baseQuery);
  const hasActiveClientParams = Boolean(q || hasActiveFilters || sort !== options.defaultSort);
  const page = parsePage(
    sp.get("page"),
    hasActiveClientParams ? 1 : options.initialPage,
  );
  const scope = parseScope(sp.get("scope"));
  const country = parseCountry(sp.get("country"));
  const remote = parseRemoteParam(sp.get("remote"));
  const company = parseRepeatedParam(sp, "company");
  const source = parseSource(sp.get("source"));
  const experience = parseExperience(sp.get("experience"));

  const filters: FeedParams = { ...options.baseQuery };
  if (scope) filters.scope = scope;
  if (country) filters.country = country;
  if (remote !== undefined) filters.remote = remote;
  if (company.length > 0) filters.company = company;
  if (source) filters.source = source;
  if (experience) filters.experience = experience;

  const canReusePrerendered =
    !q &&
    !hasActiveFilters &&
    sort === options.defaultSort &&
    page === options.initialPage;
  const usesServerPagination =
    !q &&
    !hasActiveFilters &&
    sort === options.defaultSort &&
    !sp.has("page");

  return {
    q,
    page,
    limit: options.limit,
    sort,
    filters,
    canReusePrerendered,
    usesServerPagination,
  };
}

export function loadOpportunityListingData(
  request: OpportunityListingRequest,
  revalidateSeconds?: number,
) {
  if (request.q) {
    // /search answers {items, query, total} - it carries NO `page` or `limit`,
    // unlike /feed which returns {items, total, page, limit}. Returning it raw
    // handed the results component undefined for both, and the page rendered
    // "Nothing open here" for a query the API had answered with 4,383 rows.
    // Normalise to the feed shape at the boundary rather than teaching every
    // consumer about two response types.
    return searchOpportunities(
      request.q,
      { ...request.filters, sort: request.sort },
      request.page,
      request.limit,
    ).then((response) => ({
      items: response.items,
      total: response.total,
      page: request.page,
      limit: request.limit,
    }));
  }

  return getFeed(
    {
      ...request.filters,
      sort: request.sort,
      page: request.page,
      limit: request.limit,
    },
    revalidateSeconds,
  );
}

export function opportunityListingPageHref(
  basePath: OpportunityListingPath,
  query: URLSearchParams,
  request: OpportunityListingRequest,
  page: number,
): string {
  if (request.usesServerPagination) {
    return buildPagePath(basePath, page);
  }

  const next = new URLSearchParams(query.toString());
  next.set("page", String(page));
  return opportunityListingHref(basePath, next);
}

function locationDefinitions(baseQuery: FeedParams): LocationDefinition[] {
  if (baseQuery.remote === true) {
    return [
      { value: "remote", label: "All remote", params: {} },
      {
        value: "india",
        label: "India",
        params: { scope: "domestic", country: INDIA_COUNTRY_CODE },
      },
      {
        value: "abroad",
        label: "Abroad",
        params: { scope: "abroad", country: INDIA_COUNTRY_CODE },
      },
    ];
  }

  return [
    { value: "all", label: "All", params: {} },
    {
      value: "india",
      label: "India",
      params: { scope: "domestic", country: INDIA_COUNTRY_CODE },
    },
    {
      value: "abroad",
      label: "Abroad",
      params: { scope: "abroad", country: INDIA_COUNTRY_CODE },
    },
    { value: "remote", label: "Remote", params: { remote: true } },
  ];
}

export function defaultOpportunityListingLocationOptions(
  baseQuery: FeedParams,
): FacetOption[] {
  return locationDefinitions(baseQuery).map((option) => ({
    value: option.value,
    label: option.label,
    count: 0,
  }));
}

async function totalFor(baseQuery: FeedParams, filters: FeedParams): Promise<number> {
  try {
    const data = await getFeed({ ...baseQuery, ...filters, page: 1, limit: 1 });
    return data.total;
  } catch {
    return 0;
  }
}

export async function loadOpportunityListingControlCounts(
  baseQuery: FeedParams,
): Promise<OpportunityListingCountedFilters> {
  const locations = locationDefinitions(baseQuery);
  const [locationCounts, sourceCounts, experienceCounts] = await Promise.all([
    Promise.all(locations.map((option) => totalFor(baseQuery, option.params))),
    Promise.all(
      OPPORTUNITY_SOURCE_OPTIONS.map((option) =>
        totalFor(baseQuery, { source: option.value }),
      ),
    ),
    Promise.all(
      OPPORTUNITY_EXPERIENCE_OPTIONS.map((option) =>
        totalFor(baseQuery, { experience: option.value }),
      ),
    ),
  ]);

  return {
    locationOptions: locations.map((option, index) => ({
      value: option.value,
      label: option.label,
      count: locationCounts[index] ?? 0,
    })),
    sourceOptions: OPPORTUNITY_SOURCE_OPTIONS.map((option, index) => ({
      value: option.value,
      label: option.label,
      count: sourceCounts[index] ?? 0,
    })),
    experienceOptions: OPPORTUNITY_EXPERIENCE_OPTIONS.map((option, index) => ({
      value: option.value,
      label: option.label,
      count: experienceCounts[index] ?? 0,
    })),
  };
}

export function opportunityCountLabel(count: number): string {
  return `${count} ${count === 1 ? "opportunity" : "opportunities"}`;
}
