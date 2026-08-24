import type { Metadata } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { type FeedParams, getFeed } from "@/lib/api";
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

// Every landing path that ISR serves. The revalidation route allowlist and the
// crawler's push both derive from this, so a new landing page cannot be added
// without its cache also being invalidated on the next crawl.
export const LANDING_PATHS = [
  JOBS_LANDING.basePath,
  INTERNSHIPS_LANDING.basePath,
  REMOTE_LANDING.basePath,
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
  try {
    return await getFeed(
      { ...config.query, page, limit: LANDING_LIMIT },
      LANDING_REVALIDATE,
    );
  } catch (error) {
    // These pages are static now, so they fetch at build time - which they never
    // did while they were force-dynamic. CI builds against a placeholder API URL
    // by design, so an unreachable API at build must not fail the build.
    //
    // Deliberately scoped to the build phase only. Unlike /pricing, which has a
    // meaningful FALLBACK_PLANS, there is no static stand-in for a feed: the
    // content IS the API data, so an empty render is a bad page, not a degraded
    // one. At runtime the error must propagate instead, because Next then keeps
    // serving the last good prerender rather than replacing it with an empty one.
    if (process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD) {
      return { items: [], total: 0, page, limit: LANDING_LIMIT };
    }
    throw error;
  }
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
