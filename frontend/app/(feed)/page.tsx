import { Suspense } from "react";
import { ListingSnapshotNotice, ListingUnavailable } from "@/components/ListingFeedback";
import FeedGrid from "@/components/FeedGrid";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import FeedResults from "@/components/FeedResults";
import MostViewed from "@/components/MostViewed";
import RecentlyViewed from "@/components/RecentlyViewed";
import HomeActionDesk from "@/components/HomeDesk";
import SignedOutHero from "@/components/SignedOutHero";
import StatsBar from "@/components/StatsBar";
import TopCompanies from "@/components/TopCompanies";
import { withBuildFallback } from "@/lib/buildFallback";
import { getFeed, getStats, getTrending } from "@/lib/api";
import { fetchCalendar, parseCalendarParams, todayIST } from "@/lib/hiringCalendar";
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
  return getStats(PAGE_REVALIDATE);
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
  data: FeedResultData | null;
  trendingItems: OpportunityListItem[];
  cols: number;
}) {
  if (!data) return <ListingUnavailable />;
  return (
    <>
      <div id="feed-search" className="scroll-mt-20" />
      <MostViewed items={trendingItems} />
      <FeedNavigationProvider>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 pt-10">
          <p className="text-sm text-muted-foreground">
            {typeof data.open_total === "number"
              ? `${data.open_total.toLocaleString("en-IN")} open jobs and internships`
              : `${data.total.toLocaleString("en-IN")} opportunities`}
          </p>
        </div>
        <TopCompanies />
        {data.loadedAt && <ListingSnapshotNotice loadedAt={data.loadedAt} expiresAt={data.expiresAt} />}
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

  const calendarQuery = parseCalendarParams(new URLSearchParams(), todayIST());
  const asOf = Date.parse(`${calendarQuery.from}T00:00:00+05:30`);
  const [stats, trending, data, closing, calendar] = await Promise.all([
    withBuildFallback(loadStats, data => data?.opportunities ?? 0).then(state => state.data),
    withBuildFallback(() => getTrending(undefined, PAGE_REVALIDATE, true), data => data.items.length).then(state => state.data),
    withBuildFallback(() => loadFeedData(request, PAGE_REVALIDATE), data => data.items.length).then(state => state.data),
    withBuildFallback(() => getFeed({ sort: "deadline", deadline_confidence: "explicit", limit: 6 }, PAGE_REVALIDATE), data => data.items.length).then(state => state.data),
    withBuildFallback(() => fetchCalendar(calendarQuery, undefined, PAGE_REVALIDATE), data => data.items.length).then(state => state.data),
  ]);

  return (
    <main className="mx-auto max-w-[1680px] px-4 pb-10 sm:px-6 lg:px-10 xl:px-12">
      <SignedOutHero closing={closing?.items ?? null} calendar={calendar?.items ?? null} asOf={asOf} />
      <HomeActionDesk />
      {stats && <StatsBar stats={stats} />}
      <RecentlyViewed />

      <section aria-labelledby="home-feed-title" className="pt-6">
        <h2 id="home-feed-title" className="font-serif text-2xl font-bold">Explore all opportunities</h2>
        <Suspense
          fallback={
            <DefaultFeed data={data} trendingItems={trending?.items ?? []} cols={request.cols} />
          }
        >
          <FeedResults initialData={data} trendingItems={trending?.items ?? []} />
        </Suspense>
      </section>
    </main>
  );
}
