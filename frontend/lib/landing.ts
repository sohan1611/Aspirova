import type { Metadata } from "next";
import { type FeedParams, getFeed } from "@/lib/api";
import { withBuildFallback } from "@/lib/buildFallback";
import { buildPagePath } from "@/lib/pagination";
import type { FeedResponse } from "@/lib/types";

export const LANDING_LIMIT = 20;

// The crawler runs once a day (cron "0 1 * * *"), so the underlying data changes
// once a day; anything under an hour is pure waste. Freshness is delivered by the
// crawl's revalidation push (see backend/pipeline/revalidate.py) - this window is
// only the safety net for when that push fails, since it fails open by design.
export const LANDING_REVALIDATE = 21600;

export interface LandingConfig {
  title: string;
  description: string;
  intro: string;
  basePath: string;
  query: FeedParams;
}

export const JOBS_LANDING: LandingConfig = {
  title: "Jobs",
  description:
    "Student-friendly jobs auto-discovered from public company career pages, " +
    "with each listing linking back to the original source.",
  intro:
    "Jobs, auto-discovered from public company career pages; " +
    "Aspirova links out to the original source.",
  basePath: "/jobs",
  query: { category: "job" },
};

export const INTERNSHIPS_LANDING: LandingConfig = {
  title: "Internships",
  description:
    "Student internships auto-discovered from public company career pages, " +
    "with each listing linking back to the original source.",
  intro:
    "Student internships, auto-discovered from public company career pages; " +
    "Aspirova links out to the original source.",
  basePath: "/internships",
  query: { category: "internship" },
};

export const REMOTE_LANDING: LandingConfig = {
  title: "Remote opportunities",
  description:
    "Remote opportunities auto-discovered from public company career pages, " +
    "with each listing linking back to the original source.",
  intro:
    "Remote opportunities, auto-discovered from public company career pages; " +
    "Aspirova links out to the original source.",
  basePath: "/remote",
  query: { remote: true },
};

// Landing paths that also have a /page/[n] segment. Revalidating "/jobs" does not
// touch "/jobs/page/2", so these need their route pattern invalidated as well.
export const PAGINATED_LANDING_PATHS = [
  JOBS_LANDING.basePath,
  INTERNSHIPS_LANDING.basePath,
  REMOTE_LANDING.basePath,
] as const;

// Every ISR-cached list path the crawler may invalidate. The revalidation route
// validates against exactly this set, so a new cached list page cannot be added
// without its cache also being invalidated on the next crawl. "/" and
// "/competitions" are cached too but have no paginated segment - their filtered
// views are client-rendered rather than separate routes.
export const REVALIDATABLE_LIST_PATHS = [
  "/",
  ...PAGINATED_LANDING_PATHS,
  "/competitions",
] as const;

export function totalPagesFor(total: number): number {
  return Math.max(1, Math.ceil(total / LANDING_LIMIT));
}

export function parsePageSegment(value: string): number {
  return Math.max(1, Number(value) || 1);
}

export async function loadLandingPage(
  config: LandingConfig,
  page: number,
): Promise<FeedResponse> {
  return withBuildFallback(
    () => getFeed({ ...config.query, page, limit: LANDING_LIMIT }, LANDING_REVALIDATE),
    () => ({ items: [], total: 0, page, limit: LANDING_LIMIT }),
  );
}

// Out-of-range pages return HTTP 200 while rendering the not-found page. That is
// Next 16 behaviour for notFound() inside an ISR-prerendered segment, reproduced
// locally and not fixable from here - moving notFound() into generateMetadata and
// renaming the literal `page` segment were both tried and changed nothing, and
// /companies/[slug]/page/[n] has always behaved the same way.
//
// What actually costs anything about a soft 404 is being indexed, so these pages
// are marked noindex - the same mitigation the companies route already uses, and
// verified to reach the HTML. The fetch here is deduplicated against the page's
// own identical getFeed call, so it costs no extra request.
export async function landingPageMetadata(
  config: LandingConfig,
  page: number,
): Promise<Metadata> {
  const data = await loadLandingPage(config, page);

  if (page > totalPagesFor(data.total)) {
    return {
      title: "Page not found",
      robots: { index: false, follow: false },
    };
  }

  return landingMetadata(config, page);
}

export function landingMetadata(config: LandingConfig, page: number): Metadata {
  const path = buildPagePath(config.basePath, page);
  const title = page > 1 ? `${config.title} - page ${page}` : config.title;

  return {
    title,
    description: config.description,
    alternates: { canonical: path },
  };
}
