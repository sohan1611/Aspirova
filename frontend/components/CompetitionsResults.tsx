"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  CompetitionsActiveFilterChips,
  useCompetitionFacets,
} from "@/components/CompetitionsAdvancedFilters";
import CompetitionsFilterBar from "@/components/CompetitionsFilterBar";
import EmailMatchesButton from "@/components/EmailMatchesButton";
import { hasSavedSearchParams, savedSearchParamsFromQuery } from "@/lib/savedSearchParams";
import FeedGrid from "@/components/FeedGrid";
import ListingResultsState, { listingEmptyDescription } from "@/components/ListingResultsState";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import { Button } from "@/components/ui/button";
import {
  COMPETITIONS_LIMIT,
  competitionsTotalPages,
  loadCompetitions,
  opportunityCountLabel,
  parseCompetitionsRequest,
} from "@/lib/competitionsQuery";
import type { FeedResultData } from "@/lib/feedQuery";
import { useListingResults } from "@/lib/listingResults";

interface CompetitionsResultsProps {
  // The statically prerendered default view, reused whenever the visitor's query
  // string describes that same view - which is the point of this component.
  initialData: FeedResultData;
}

function pageHref(searchParams: URLSearchParams, page: number): string {
  const next = new URLSearchParams(searchParams.toString());
  next.set("page", String(page));
  return `/competitions?${next.toString()}`;
}

export default function CompetitionsResults({ initialData }: CompetitionsResultsProps) {
  const searchParams = useSearchParams();
  // During the static prerender this yields an empty set, which parses to exactly
  // the default request - so the build renders initialData into the HTML.
  const query = new URLSearchParams(searchParams.toString());
  const request = parseCompetitionsRequest(query);
  const { facets, facetsStatus } = useCompetitionFacets();

  const queryKey = query.toString();

  // Results are held outside React, keyed by the query string - see
  // lib/listingResults.ts for why component state could not hold them on this
  // statically prerendered, useSearchParams-reading route.
  const { settled, retry } = useListingResults(
    "/competitions",
    queryKey,
    !request.canReusePrerendered,
    () => loadCompetitions(request),
    initialData,
  );

  const isLoading = !request.canReusePrerendered && (!settled || settled.status === "loading");
  const data = settled?.data ?? initialData;

  const totalPages = competitionsTotalPages(data.total);

  return (
    <FeedNavigationProvider>
      <div className="mb-5 mt-6 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4 sm:mt-8">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <p className="eyebrow">Open arena</p>
          <p className="tnum text-sm text-muted-foreground">
            {opportunityCountLabel(data.total, data.open_total)}
          </p>
        </div>

        {hasSavedSearchParams(query) && (
          <EmailMatchesButton params={savedSearchParamsFromQuery({ ...request, kind: "competitions" })} />
        )}
        <CompetitionsFilterBar facets={facets} facetsStatus={facetsStatus} />
      </div>

      <CompetitionsActiveFilterChips facets={facets} />

      <ListingResultsState
        loading={isLoading}
        error={settled?.error ?? null}
        retry={retry}
        retrying={settled?.retrying ?? false}
        hasItems={data.items.length > 0}
        skeletonCount={data.items.length || Math.min(COMPETITIONS_LIMIT, 9)}
        cols={3}
        competition
      >
        <FeedGrid
          items={data.items}
          cols={3}
          competitionSkeleton
          skeletonCount={data.items.length || Math.min(COMPETITIONS_LIMIT, 9)}
          emptyHref="/competitions"
          emptyActionLabel="Clear filters"
          emptyTitle="The next challenge is still being discovered."
          emptyDescription={listingEmptyDescription(
            query,
            "Check back soon as Aspirova indexes more competitions and hackathons. Try a broader search or clear your filters.",
          )}
        />
      </ListingResultsState>

      {!isLoading && !settled?.error && totalPages > 1 && (
        <nav
          className="mt-8 flex flex-wrap items-center justify-center gap-3 sm:gap-4"
          aria-label="Competitions pagination"
        >
          <Button
            variant="outline"
            size="sm"
            disabled={request.page <= 1}
            asChild={request.page > 1}
          >
            {request.page > 1 ? (
              <Link href={pageHref(query, request.page - 1)} rel="prev">
                Previous
              </Link>
            ) : (
              "Previous"
            )}
          </Button>
          <span className="tnum text-sm text-muted-foreground">
            Page {request.page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={request.page >= totalPages}
            asChild={request.page < totalPages}
          >
            {request.page < totalPages ? (
              <Link href={pageHref(query, request.page + 1)} rel="next">
                Next
              </Link>
            ) : (
              "Next"
            )}
          </Button>
        </nav>
      )}
    </FeedNavigationProvider>
  );
}
