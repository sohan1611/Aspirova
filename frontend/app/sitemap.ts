import type { MetadataRoute } from "next";

const SITE_URL = "https://www.aspirova.org";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const STATIC_ROUTES = [
  "/",
  "/pricing",
  "/resume",
  "/copilot",
  "/internships",
  "/remote",
  "/jobs",
  "/companies",
  "/competitions",
  "/research",
] as const;

export const revalidate = 300;

interface SitemapOpportunity {
  slug: string;
  last_seen_at: string;
}

interface SitemapCompany {
  slug: string;
}

type SitemapEntry = MetadataRoute.Sitemap[number];

function staticEntries(): MetadataRoute.Sitemap {
  return STATIC_ROUTES.map((route) => ({
    url: route === "/" ? SITE_URL : `${SITE_URL}${route}`,
  }));
}

async function fetchSitemapOpportunities(): Promise<SitemapOpportunity[]> {
  const response = await fetch(`${API_URL}/sitemap-opportunities`, {
    next: { revalidate: 300 },
  });
  if (!response.ok) {
    throw new Error(`Failed to load sitemap opportunities: ${response.status}`);
  }
  return response.json();
}

async function fetchSitemapCompanies(): Promise<SitemapCompany[]> {
  const response = await fetch(`${API_URL}/sitemap-companies`, {
    next: { revalidate: 300 },
  });
  if (!response.ok) {
    throw new Error(`Failed to load sitemap companies: ${response.status}`);
  }
  return response.json();
}

function lastModifiedFrom(value: string): Date | undefined {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  let opportunities: SitemapOpportunity[] = [];
  let companies: SitemapCompany[] = [];
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
  ];
}
