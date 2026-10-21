import type { MetadataRoute } from "next";
import {
  getOpportunitySitemapIds,
  sitemapSiteUrl,
} from "@/lib/sitemap";

export const revalidate = 86400;

export default async function robots(): Promise<MetadataRoute.Robots> {
  const opportunitySitemaps = (await getOpportunitySitemapIds()).map(({ id }) =>
    sitemapSiteUrl(`/opportunity/sitemap/${id}.xml`),
  );

  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: "/style",
    },
    sitemap: [sitemapSiteUrl("/sitemap.xml"), ...opportunitySitemaps],
  };
}
