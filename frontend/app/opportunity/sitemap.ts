import type { MetadataRoute } from "next";
import {
  fetchSitemapOpportunities,
  getOpportunitySitemapIds,
  lastModifiedFrom,
  sitemapSiteUrl,
} from "@/lib/sitemap";

export const revalidate = 86400;

type SitemapEntry = MetadataRoute.Sitemap[number];

export async function generateSitemaps(): Promise<{ id: number }[]> {
  return getOpportunitySitemapIds();
}

export default async function sitemap({
  id,
}: {
  id: Promise<string>;
}): Promise<MetadataRoute.Sitemap> {
  const page = Number(await id);
  if (!Number.isInteger(page) || page < 0) return [];

  try {
    const opportunities = await fetchSitemapOpportunities(page);
    return opportunities
      .filter((opportunity) => opportunity.slug && opportunity.last_seen_at)
      .map((opportunity): SitemapEntry => {
        const entry: SitemapEntry = {
          url: sitemapSiteUrl(
            `/opportunity/${encodeURIComponent(opportunity.slug)}`,
          ),
        };
        const lastModified = lastModifiedFrom(opportunity.last_seen_at);
        if (lastModified) {
          entry.lastModified = lastModified;
        }
        return entry;
      });
  } catch {
    return [];
  }
}
