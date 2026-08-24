import type { Metadata } from "next";
import { Suspense } from "react";
import CompetitionsResults from "@/components/CompetitionsResults";
import FeedGrid from "@/components/FeedGrid";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import { withBuildFallback } from "@/lib/buildFallback";
import {
  COMPETITIONS_LIMIT,
  defaultCompetitionsRequest,
  loadCompetitions,
  opportunityCountLabel,
} from "@/lib/competitionsQuery";
import type { FeedResultData } from "@/lib/feedQuery";

const DESCRIPTION =
  "Competitions and hackathons for students, auto-discovered from public sources and tracked through their registration deadlines.";
const INTRO =
  "Find competitions and hackathons worth entering, and register before their deadlines close.";

// ISR. This page no longer reads `searchParams` - that is what forced a full
// server render on every visit. Filtered views are handled by CompetitionsResults
// after hydration. Literal, not the imported constant, because Next only honours
// a statically analysable value here; keep it in sync with
// COMPETITIONS_REVALIDATE.
export const revalidate = 21600;

const PAGE_REVALIDATE = 21600;

export const metadata: Metadata = {
  title: "Competitions & hackathons",
  description: DESCRIPTION,
  alternates: { canonical: "/competitions" },
};

// Prerendered into the static HTML as the Suspense fallback below.
// CompetitionsResults calls useSearchParams, which in a static route pushes its
// whole subtree to the client - without this the listings would be missing from
// the HTML crawlers see. Neither FeedGrid nor the navigation provider calls
// useSearchParams, so this renders on the server. CompetitionsFilterBar does, so
// it is deliberately absent here and arrives on hydration.
function DefaultCompetitions({ data }: { data: FeedResultData }) {
  return (
    <FeedNavigationProvider>
      <div className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <p className="eyebrow">Open arena</p>
          <p className="tnum text-sm text-muted-foreground">
            {opportunityCountLabel(data.total)}
          </p>
        </div>
      </div>

      <FeedGrid
        items={data.items}
        cols={3}
        skeletonCount={data.items.length || Math.min(COMPETITIONS_LIMIT, 9)}
        emptyHref="/competitions"
        emptyActionLabel="Clear filters"
        emptyTitle="The next challenge is still being discovered."
        emptyDescription="Check back soon as Aspirova indexes more competitions and hackathons."
      />
    </FeedNavigationProvider>
  );
}

export default async function CompetitionsPage() {
  const request = defaultCompetitionsRequest();
  const data = await withBuildFallback(
    () => loadCompetitions(request, PAGE_REVALIDATE),
    () => ({ items: [], total: 0 }),
  );

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">THE ARENA</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Competitions &amp; hackathons
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {INTRO}
        </p>
      </header>

      <Suspense fallback={<DefaultCompetitions data={data} />}>
        <CompetitionsResults initialData={data} />
      </Suspense>
    </main>
  );
}
