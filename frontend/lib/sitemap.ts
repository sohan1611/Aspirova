const SITE_URL = "https://www.aspirova.org";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const REVALIDATE_SECONDS = 86400;
const FALLBACK_OPPORTUNITY_SITEMAP_COUNT = 8;
const SPARE_OPPORTUNITY_SITEMAPS = 2;

export interface SitemapOpportunity {
  slug: string;
  last_seen_at: string;
}

export interface OpportunitySitemapId {
  id: number;
}

interface SitemapOpportunityCount {
  total: number;
  page_size: number;
}

export function sitemapSiteUrl(path = ""): string {
  if (!path || path === "/") return SITE_URL;
  return `${SITE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export function sitemapApiUrl(path: string): string {
  return `${API_URL.replace(/\/$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}

function sitemapIds(count: number): OpportunitySitemapId[] {
  return Array.from({ length: count }, (_, id) => ({ id }));
}

function isSitemapOpportunityCount(value: unknown): value is SitemapOpportunityCount {
  if (!value || typeof value !== "object") return false;
  const count = value as Partial<SitemapOpportunityCount>;
  return (
    Number.isInteger(count.total) &&
    (count.total ?? -1) >= 0 &&
    Number.isInteger(count.page_size) &&
    (count.page_size ?? 0) > 0
  );
}

export async function getOpportunitySitemapIds(): Promise<OpportunitySitemapId[]> {
  try {
    const response = await fetch(sitemapApiUrl("/sitemap-opportunities/count"), {
      next: { revalidate: REVALIDATE_SECONDS },
    });
    if (!response.ok) {
      throw new Error(`Failed to load sitemap opportunity count: ${response.status}`);
    }

    const count: unknown = await response.json();
    if (!isSitemapOpportunityCount(count)) {
      throw new Error("Invalid sitemap opportunity count response");
    }

    const populatedPages = Math.ceil(count.total / count.page_size);
    return sitemapIds(populatedPages + SPARE_OPPORTUNITY_SITEMAPS);
  } catch {
    return sitemapIds(FALLBACK_OPPORTUNITY_SITEMAP_COUNT);
  }
}

export async function fetchSitemapOpportunities(
  page: number,
): Promise<SitemapOpportunity[]> {
  const response = await fetch(
    sitemapApiUrl(`/sitemap-opportunities?page=${page}`),
    { next: { revalidate: REVALIDATE_SECONDS } },
  );
  if (!response.ok) {
    throw new Error(`Failed to load sitemap opportunities: ${response.status}`);
  }
  return response.json();
}

export function lastModifiedFrom(value: string): Date | undefined {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}
