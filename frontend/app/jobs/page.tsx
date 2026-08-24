import type { Metadata } from "next";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import {
  JOBS_LANDING,
  LANDING_LIMIT,
  landingMetadata,
  loadLandingPage,
} from "@/lib/landing";

// ISR. This page no longer reads `searchParams` - that is what previously forced
// it to render per request, and why `dynamic = "force-dynamic"` was a no-op fix.
// Pagination now lives at /jobs/page/[n]. Literal, not the imported
// LANDING_REVALIDATE, because Next only honours a statically analysable value
// here; keep the two in sync.
export const revalidate = 21600;

export const metadata: Metadata = landingMetadata(JOBS_LANDING, 1);

export default async function JobsPage() {
  const data = await loadLandingPage(JOBS_LANDING, 1);

  return (
    <OpportunityLandingPage
      title={JOBS_LANDING.title}
      intro={JOBS_LANDING.intro}
      items={data.items}
      total={data.total}
      page={1}
      limit={LANDING_LIMIT}
      basePath={JOBS_LANDING.basePath}
    />
  );
}
