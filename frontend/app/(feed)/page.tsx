import { Suspense } from "react";
import FeedGrid from "@/components/FeedGrid";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import FeedResults from "@/components/FeedResults";
import MostViewed from "@/components/MostViewed";
import RecentlyViewed from "@/components/RecentlyViewed";
import SignedInWelcome from "@/components/SignedInWelcome";
import SignedOutHero from "@/components/SignedOutHero";
import StatsBar from "@/components/StatsBar";
import TopCompanies from "@/components/TopCompanies";
import { getStats, getTrending } from "@/lib/api";
import { withBuildFallback } from "@/lib/buildFallback";
import { type FeedResultData, defaultFeedRequest, loadFeedData } from "@/lib/feedQuery";
import type { OpportunityListItem, StatsResponse } from "@/lib/types";

// ISR. This page no longer reads `searchParams` - that is what forced a full
// server render on every visit, which is what exhausted the Vercel CPU budget.
// Filtered and search URLs are handled by FeedResults after hydration.
// Literal, not an imported constant, because Next only honours a statically
// analysable value here.
export const revalidate = 21600;

// Every fetch below passes the page's own window. A fetch revalidate lower than
// the page's silently caps the route's ISR window, so leaving getStats at its 300s
// default would have quietly reduced this page to a 5-minute cache.
const PAGE_REVALIDATE = 21600;

async function loadStats(): Promise<StatsResponse | null> {
  try {
    return await getStats(PAGE_REVALIDATE);
  } catch {
    return null;
  }
}

// Prerendered into the static HTML as the Suspense fallback below. FeedResults
// calls useSearchParams, which in a static route pushes its whole subtree to the
// client - so without this fallback the listings would vanish from the HTML that
// crawlers see. None of the components here call useSearchParams, so this renders
// on the server. It is the default feed, which is what a bare "/" should show.
function DefaultFeed({
  data,
  trendingItems,
  cols,
}: {
  data: FeedResultData;
  trendingItems: OpportunityListItem[];
  cols: number;
}) {
  return (
    <>
      <MostViewed items={trendingItems} />
      <FeedNavigationProvider>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 pt-10">
          <p className="text-sm text-muted-foreground">{data.total} opportunities</p>
        </div>
        <TopCompanies />
        <FeedGrid
          items={data.items}
          cols={cols}
          skeletonCount={data.items.length || 9}
        />
      </FeedNavigationProvider>
    </>
  );
}

export default async function HomePage() {
  const request = defaultFeedRequest();

  const [stats, trending, data] = await Promise.all([
    loadStats(),
    getTrending(undefined, PAGE_REVALIDATE),
    withBuildFallback(
      () => loadFeedData(request, PAGE_REVALIDATE),
      () => ({ items: [], total: 0 }),
    ),
  ]);

  return (
    <main className="mx-auto max-w-[1680px] px-4 pb-10 sm:px-6 lg:px-10 xl:px-12">
      <SignedOutHero />
      <SignedInWelcome />
      {stats && <StatsBar stats={stats} />}
      <RecentlyViewed />

      <Suspense
        fallback={
          <DefaultFeed data={data} trendingItems={trending.items} cols={request.cols} />
        }
      >
        <FeedResults initialData={data} trendingItems={trending.items} />
      </Suspense>
    </main>
  );
}
