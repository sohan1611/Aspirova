import type { Metadata } from "next";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import {
  INTERNSHIPS_LANDING,
  LANDING_LIMIT,
  landingMetadata,
  loadLandingPage,
} from "@/lib/landing";

// ISR - see app/jobs/page.tsx for why the `searchParams` removal is what makes
// this cacheable. Literal, not the imported LANDING_REVALIDATE, because Next only
// honours a statically analysable value here; keep the two in sync.
export const revalidate = 21600;

export const metadata: Metadata = landingMetadata(INTERNSHIPS_LANDING, 1);

export default async function InternshipsPage() {
  const data = await loadLandingPage(INTERNSHIPS_LANDING, 1);

  return (
    <OpportunityLandingPage
      title={INTERNSHIPS_LANDING.title}
      intro={INTERNSHIPS_LANDING.intro}
      items={data.items}
      total={data.total}
      page={1}
      limit={LANDING_LIMIT}
      basePath={INTERNSHIPS_LANDING.basePath}
    />
  );
}
