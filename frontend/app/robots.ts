import type { MetadataRoute } from "next";

const SITE_URL = "https://aspirova.vercel.app";

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
