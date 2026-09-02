"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import FeedGrid from "@/components/FeedGrid";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import {
  OpportunityListingActiveFilterChips,
  OpportunityListingFilterBar,
  useOpportunityListingFacets,
} from "@/components/OpportunityListingFilters";
import { Button } from "@/components/ui/button";
import type { FeedParams } from "@/lib/api";
import type { FeedResultData } from "@/lib/feedQuery";
import {
  loadOpportunityListingData,
  opportunityCountLabel,
  opportunityListingPageHref,
  parseOpportunityListingRequest,
  type OpportunityListingPath,
  type OpportunityListingSort,
} from "@/lib/opportunityListingQuery";

interface OpportunityLandingResultsProps {
  initialData: FeedResultData;
  basePath: OpportunityListingPath;
  baseQuery: FeedParams;
  initialPage: number;
  limit: number;
  defaultSort: OpportunityListingSort;
}

export default function OpportunityLandingResults({
  initialData,
  basePath,
  baseQuery,
  initialPage,
  limit,
  defaultSort,
}: OpportunityLandingResultsProps) {
  const searchParams = useSearchParams();
  const query = new URLSearchParams(searchParams.toString());
  const request = parseOpportunityListingRequest(query, {
    basePath,
    baseQuery,
    defaultSort,
    initialPage,
    limit,
  });
  const { data: facetsData, facetsStatus } = useOpportunityListingFacets(baseQuery);
  const [settled, setSettled] = useState<{
    key: string;
    data: FeedResultData | null;
  } | null>(null);
  const queryKey = query.toString();

  useEffect(() => {
    if (request.canReusePrerendered) return;

    let cancelled = false;

    loadOpportunityListingData(request)
      .then((response) => {
        if (!cancelled) setSettled({ key: queryKey, data: response });
      })
      .catch(() => {
        if (!cancelled) setSettled({ key: queryKey, data: null });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  const isSettled = settled?.key === queryKey;
  const isLoading = !request.canReusePrerendered && !isSettled;
  const data =
    !request.canReusePrerendered && isSettled && settled?.data
      ? settled.data
      : initialData;
  const totalPages = Math.max(1, Math.ceil(data.total / request.limit));

  return (
    <FeedNavigationProvider>
      <div className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <p className="eyebrow">Open opportunities</p>
          <p className="tnum text-sm text-muted-foreground">
            {opportunityCountLabel(data.total)}
          </p>
        </div>

        <OpportunityListingFilterBar
          basePath={basePath}
          baseQuery={baseQuery}
          defaultSort={defaultSort}
          data={facetsData}
          facetsStatus={facetsStatus}
        />
      </div>

      <OpportunityListingActiveFilterChips
        basePath={basePath}
        baseQuery={baseQuery}
        data={facetsData}
      />

      <FeedGrid
        items={isLoading ? [] : data.items}
        cols={3}
        skeletonCount={data.items.length || Math.min(request.limit, 9)}
        emptyHref={basePath}
        emptyActionLabel="Clear filters"
        emptyTitle="Nothing open here - yet."
        emptyDescription="Aspirova is always discovering more from public sources. Try a broader search or clear your filters."
      />

      {totalPages > 1 && (
        <nav
          className="mt-8 flex flex-wrap items-center justify-center gap-3 sm:gap-4"
          aria-label="Opportunities pagination"
        >
          <Button
            variant="outline"
            size="sm"
            disabled={request.page <= 1}
            asChild={request.page > 1}
          >
            {request.page > 1 ? (
              <Link href={opportunityListingPageHref(basePath, query, request, request.page - 1)} rel="prev">
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
              <Link href={opportunityListingPageHref(basePath, query, request, request.page + 1)} rel="next">
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
