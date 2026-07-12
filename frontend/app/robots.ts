import type { MetadataRoute } from "next";

const SITE_URL = "https://www.aspirova.org";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: "/style",
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
