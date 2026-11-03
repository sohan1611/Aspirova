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
    // Keep search crawlers off image renders while allowing shared-link previews.
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/style", "/opportunity/*/opengraph-image"],
      },
      {
        userAgent: [
          "facebookexternalhit", "WhatsApp", "TelegramBot", "Twitterbot",
          "LinkedInBot", "Slackbot", "Discordbot",
        ],
        allow: "/",
        disallow: "/style",
      },
    ],
    sitemap: [sitemapSiteUrl("/sitemap.xml"), ...opportunitySitemaps],
  };
}
