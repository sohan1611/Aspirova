"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import CompetitionsFilterBar from "@/components/CompetitionsFilterBar";
import FeedGrid from "@/components/FeedGrid";
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

  // One keyed state with both flags derived from it. `data: null` records a
  // failed request on purpose: keying only successes would leave a failed fetch
  // showing skeletons forever.
  const [settled, setSettled] = useState<{
    key: string;
    data: FeedResultData | null;
  } | null>(null);
  const queryKey = query.toString();

  useEffect(() => {
    if (request.canReusePrerendered) return;

    let cancelled = false;

    loadCompetitions(request)
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
  // On a failed fetch keep the previous listings rather than blanking the grid;
  // the empty state would otherwise claim nothing matched when the real problem
  // was a dead request.
  const data =
    !request.canReusePrerendered && isSettled && settled?.data ? settled.data : initialData;

  const totalPages = competitionsTotalPages(data.total);

  return (
    <FeedNavigationProvider>
      <div className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <p className="eyebrow">Open arena</p>
          <p className="tnum text-sm text-muted-foreground">
            {opportunityCountLabel(data.total)}
          </p>
        </div>

        <CompetitionsFilterBar />
      </div>

      <FeedGrid
        items={isLoading ? [] : data.items}
        cols={3}
        skeletonCount={data.items.length || Math.min(COMPETITIONS_LIMIT, 9)}
        emptyHref="/competitions"
        emptyActionLabel="Clear filters"
        emptyTitle="The next challenge is still being discovered."
        emptyDescription="Check back soon as Aspirova indexes more competitions and hackathons."
      />

      {totalPages > 1 && (
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
