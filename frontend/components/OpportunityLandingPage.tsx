import Link from "next/link";
import { Suspense, type ReactNode } from "react";
import FeedGrid from "@/components/FeedGrid";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import OpportunityLandingResults from "@/components/OpportunityLandingResults";
import { Button } from "@/components/ui/button";
import type { FeedParams } from "@/lib/api";
import { buildPagePath } from "@/lib/pagination";
import type { OpportunityListItem } from "@/lib/types";
import {
  opportunityCountLabel,
  type OpportunityListingPath,
  type OpportunityListingSort,
} from "@/lib/opportunityListingQuery";

interface OpportunityLandingPageProps {
  title: string;
  intro: string;
  items: OpportunityListItem[];
  total: number;
  openTotal?: number | null;
  page: number;
  limit: number;
  basePath: OpportunityListingPath;
  query: FeedParams;
  defaultSort?: OpportunityListingSort;
  children?: ReactNode;
}

function DefaultOpportunityLanding({
  items,
  total,
  openTotal,
  page,
  limit,
  basePath,
}: {
  items: OpportunityListItem[];
  total: number;
  openTotal?: number | null;
  page: number;
  limit: number;
  basePath: OpportunityListingPath;
}) {
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <FeedNavigationProvider>
      <div className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <p className="eyebrow">Open opportunities</p>
          <p className="tnum text-sm text-muted-foreground">
            {opportunityCountLabel(total, openTotal)}
          </p>
        </div>
      </div>

      <FeedGrid
        items={items}
        cols={3}
        skeletonCount={items.length || Math.min(limit, 9)}
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
          <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
            {page > 1 ? (
              <Link href={buildPagePath(basePath, page - 1)} rel="prev">
                Previous
              </Link>
            ) : (
              "Previous"
            )}
          </Button>
          <span className="tnum text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            asChild={page < totalPages}
          >
            {page < totalPages ? (
              <Link href={buildPagePath(basePath, page + 1)} rel="next">
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

export default function OpportunityLandingPage({
  title,
  intro,
  items,
  total,
  openTotal,
  page,
  limit,
  basePath,
  query,
  // All current listing pages use this default, mapped to Newest + For students ON.
  defaultSort = "student",
  children,
}: OpportunityLandingPageProps) {
  const initialData = { items, total, open_total: openTotal };

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <h1 className="font-serif text-4xl font-bold leading-tight tracking-tight text-foreground sm:text-5xl">
          {title}
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {intro}
        </p>
      </header>

      <Suspense
        fallback={
          <DefaultOpportunityLanding
            items={items}
            total={total}
            openTotal={openTotal}
            page={page}
            limit={limit}
            basePath={basePath}
          />
        }
      >
        <OpportunityLandingResults
          initialData={initialData}
          basePath={basePath}
          baseQuery={query}
          initialPage={page}
          limit={limit}
          defaultSort={defaultSort}
        />
      </Suspense>
      {children}
    </main>
  );
}
