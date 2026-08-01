import type { MetadataRoute } from "next";

const SITE_URL = "https://www.aspirova.org";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const STATIC_ROUTES = [
  "/",
  "/pricing",
  "/terms",
  "/privacy",
  "/refunds",
  "/contact",
  "/resume",
  "/copilot",
  "/internships",
  "/remote",
  "/jobs",
  "/companies",
  "/programmes",
  "/competitions",
  "/research",
] as const;

export const revalidate = 86400;

interface SitemapOpportunity {
  slug: string;
  last_seen_at: string;
}

interface SitemapCompany {
  slug: string;
}

interface SitemapProgramme {
  slug: string;
}

interface SitemapProgrammeListResponse {
  items: SitemapProgramme[];
  total: number;
  page: number;
  limit: number;
}

type SitemapEntry = MetadataRoute.Sitemap[number];

function staticEntries(): MetadataRoute.Sitemap {
  return STATIC_ROUTES.map((route) => ({
    url: route === "/" ? SITE_URL : `${SITE_URL}${route}`,
  }));
}

async function fetchSitemapOpportunities(): Promise<SitemapOpportunity[]> {
  const response = await fetch(`${API_URL}/sitemap-opportunities`, {
        next: { revalidate: 86400 },
  });
  if (!response.ok) {
    throw new Error(`Failed to load sitemap opportunities: ${response.status}`);
  }
  return response.json();
}

async function fetchSitemapCompanies(): Promise<SitemapCompany[]> {
  const response = await fetch(`${API_URL}/sitemap-companies`, {
        next: { revalidate: 86400 },
  });
  if (!response.ok) {
    throw new Error(`Failed to load sitemap companies: ${response.status}`);
  }
  return response.json();
}

async function fetchSitemapProgrammes(): Promise<SitemapProgramme[]> {
  const limit = 100;
  const programmes: SitemapProgramme[] = [];
  let page = 1;
  let total = 0;

  do {
    const search = new URLSearchParams({
      page: String(page),
      limit: String(limit),
    });
    const response = await fetch(`${API_URL}/programmes?${search.toString()}`, {
        next: { revalidate: 86400 },
    });
    if (!response.ok) {
      throw new Error(`Failed to load sitemap programmes: ${response.status}`);
    }

    const data = (await response.json()) as SitemapProgrammeListResponse;
    programmes.push(...data.items);
    total = data.total;
    page += 1;

    if (data.items.length === 0) break;
  } while (programmes.length < total && page <= 20);

  return programmes;
}

function lastModifiedFrom(value: string): Date | undefined {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  let opportunities: SitemapOpportunity[] = [];
  let companies: SitemapCompany[] = [];
  let programmes: SitemapProgramme[] = [];
  try {
    opportunities = await fetchSitemapOpportunities();
  } catch {
    opportunities = [];
  }
  try {
    companies = await fetchSitemapCompanies();
  } catch {
    companies = [];
  }
  try {
    programmes = await fetchSitemapProgrammes();
  } catch {
    programmes = [];
  }

  return [
    ...staticEntries(),
    ...opportunities
      .filter((opportunity) => opportunity.slug && opportunity.last_seen_at)
      .map((opportunity): SitemapEntry => {
        const entry: SitemapEntry = {
          url: `${SITE_URL}/opportunity/${encodeURIComponent(opportunity.slug)}`,
        };
        const lastModified = lastModifiedFrom(opportunity.last_seen_at);
        if (lastModified) {
          entry.lastModified = lastModified;
        }
        return entry;
      }),
    ...companies
      .filter((company) => company.slug)
      .map((company): SitemapEntry => {
        return {
          url: `${SITE_URL}/companies/${encodeURIComponent(company.slug)}`,
        };
      }),
    ...programmes
      .filter((programme) => programme.slug)
      .map((programme): SitemapEntry => {
        return {
          url: `${SITE_URL}/programme/${encodeURIComponent(programme.slug)}`,
        };
      }),
  ];
}
