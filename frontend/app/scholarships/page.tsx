import type { Metadata } from "next";
import Link from "next/link";
import OpportunityLandingPage from "@/components/OpportunityLandingPage";
import ProgrammeCard from "@/components/ProgrammeCard";
import { getProgrammes } from "@/lib/api";
import { withBuildFallback } from "@/lib/buildFallback";
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
  const programmes = await withBuildFallback(
    () => getProgrammes({ category: ["scholarship", "fellowship"], limit: 100 }, revalidate),
    () => ({ items: [], total: 0, page: 1, limit: 100 }),
  );

  return (
    <OpportunityLandingPage
      title={SCHOLARSHIPS_LANDING.title}
      intro={SCHOLARSHIPS_LANDING.intro}
      items={data.items}
      total={data.total}
      openTotal={data.open_total}
      page={1}
      limit={LANDING_LIMIT}
      basePath={SCHOLARSHIPS_LANDING.basePath}
      query={SCHOLARSHIPS_LANDING.query}
    >
      {programmes.items.length > 0 && (
        <section className="mt-14" aria-labelledby="scholarship-programmes-heading">
          <h2 id="scholarship-programmes-heading" className="font-serif text-3xl font-semibold tracking-tight">
            Scholarship and fellowship programmes
          </h2>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            These run on a regular cycle. Dates are the usual window, so confirm on the official site.
          </p>
          <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {programmes.items.map((programme) => <ProgrammeCard key={programme.slug} programme={programme} />)}
          </div>
          <Link href="/programmes" className="mt-6 inline-flex text-sm text-primary underline underline-offset-4">
            All programmes →
          </Link>
        </section>
      )}
    </OpportunityLandingPage>
  );
}
