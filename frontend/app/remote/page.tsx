import type { Metadata } from "next";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import {
  LANDING_LIMIT,
  REMOTE_LANDING,
  landingMetadata,
  loadLandingPage,
} from "@/lib/landing";

// ISR - see app/jobs/page.tsx for why the `searchParams` removal is what makes
// this cacheable. Literal, not the imported LANDING_REVALIDATE, because Next only
// honours a statically analysable value here; keep the two in sync.
export const revalidate = 21600;

export const metadata: Metadata = landingMetadata(REMOTE_LANDING, 1);

export default async function RemotePage() {
  const data = await loadLandingPage(REMOTE_LANDING, 1);

  return (
    <OpportunityLandingPage
      title={REMOTE_LANDING.title}
      intro={REMOTE_LANDING.intro}
      items={data.items}
      total={data.total}
      page={1}
      limit={LANDING_LIMIT}
      basePath={REMOTE_LANDING.basePath}
    />
  );
}
