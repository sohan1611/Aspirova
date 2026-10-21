import type { MetadataRoute } from "next";
import { sitemapApiUrl, sitemapSiteUrl } from "@/lib/sitemap";

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
    url: sitemapSiteUrl(route),
  }));
}

async function fetchSitemapCompanies(): Promise<SitemapCompany[]> {
  const response = await fetch(sitemapApiUrl("/sitemap-companies"), {
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
    const response = await fetch(
      sitemapApiUrl(`/programmes?${search.toString()}`),
      { next: { revalidate: 86400 } },
    );
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

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  let companies: SitemapCompany[] = [];
  let programmes: SitemapProgramme[] = [];
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
    ...companies
      .filter((company) => company.slug)
      .map((company): SitemapEntry => {
        return {
          url: sitemapSiteUrl(`/companies/${encodeURIComponent(company.slug)}`),
        };
      }),
    ...programmes
      .filter((programme) => programme.slug)
      .map((programme): SitemapEntry => {
        return {
          url: sitemapSiteUrl(`/programme/${encodeURIComponent(programme.slug)}`),
        };
      }),
  ];
}
