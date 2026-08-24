import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // An unrelated package-lock.json elsewhere on this machine was confusing
  // Turbopack's auto-detected workspace root. This repo's frontend/ is the
  // actual root.
  turbopack: {
    root: path.join(__dirname),
  },
  // Page 1 of a paginated segment is the base path, and these rules are what
  // actually enforce that. The `redirect()` call in each page/[n] component does
  // NOT fire for these routes once they are ISR-prerendered - verified in
  // production, where /jobs/page/1 rendered the not-found page with a 200 while
  // /companies/:slug/page/1 correctly returned 308 purely because of the rule
  // below. Adding a landing page means adding its rule here too.
  async redirects() {
    return [
      {
        source: "/companies/:slug/page/1",
        destination: "/companies/:slug",
        permanent: true,
      },
      {
        source: "/jobs/page/1",
        destination: "/jobs",
        permanent: true,
      },
      {
        source: "/internships/page/1",
        destination: "/internships",
        permanent: true,
      },
      {
        source: "/remote/page/1",
        destination: "/remote",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
