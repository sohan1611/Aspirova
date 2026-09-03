import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import {
  JOBS_LANDING,
  LANDING_LIMIT,
  landingPageMetadata,
  loadLandingPage,
  parsePageSegment,
  totalPagesFor,
} from "@/lib/landing";

// Literal, not the imported LANDING_REVALIDATE, because Next only honours a
// statically analysable value here; keep the two in sync.
export const revalidate = 21600;

// Registers the route for on-demand ISR without prerendering anything at build
// time. Without this export, Next leaves a dynamic segment fully per-request and
// the `revalidate` above is silently ignored - verified previously via
// .next/prerender-manifest.json, where dynamicRoutes stayed empty. Returning []
// also avoids building a static mirror of the corpus for the bot that walks deep
// pages (see BROWSE-CACHING-2026-08-24-HANDOFF.md sec 5).
export async function generateStaticParams(): Promise<{ n: string }[]> {
  return [];
}

interface PageProps {
  params: Promise<{ n: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { n } = await params;
  return landingPageMetadata(JOBS_LANDING, parsePageSegment(n));
}

export default async function JobsPaginatedPage({ params }: PageProps) {
  const { n } = await params;
  const page = parsePageSegment(n);
  if (page <= 1) {
    redirect(JOBS_LANDING.basePath);
  }

  const data = await loadLandingPage(JOBS_LANDING, page);
  if (page > totalPagesFor(data.total)) {
    notFound();
  }

  return (
    <OpportunityLandingPage
      title={JOBS_LANDING.title}
      intro={JOBS_LANDING.intro}
      items={data.items}
      total={data.total}
      page={page}
      limit={LANDING_LIMIT}
      basePath={JOBS_LANDING.basePath}
      query={JOBS_LANDING.query}
    />
  );
}
