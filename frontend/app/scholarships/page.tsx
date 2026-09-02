import type { Metadata } from "next";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import {
  SCHOLARSHIPS_LANDING,
  LANDING_LIMIT,
  landingMetadata,
  loadLandingPage,
} from "@/lib/landing";

// ISR - see app/jobs/page.tsx for why the `searchParams` removal is what makes
// this cacheable. Literal, not the imported LANDING_REVALIDATE, because Next only
// honours a statically analysable value here; keep the two in sync.
export const revalidate = 21600;

export const metadata: Metadata = landingMetadata(SCHOLARSHIPS_LANDING, 1);

export default async function ScholarshipsPage() {
  const data = await loadLandingPage(SCHOLARSHIPS_LANDING, 1);

  return (
    <OpportunityLandingPage
      title={SCHOLARSHIPS_LANDING.title}
      intro={SCHOLARSHIPS_LANDING.intro}
      items={data.items}
      total={data.total}
      page={1}
      limit={LANDING_LIMIT}
      basePath={SCHOLARSHIPS_LANDING.basePath}
      query={SCHOLARSHIPS_LANDING.query}
    />
  );
}
