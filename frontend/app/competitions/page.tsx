import type { Metadata } from "next";
import Link from "next/link";
import CompetitionsFilterBar from "@/components/CompetitionsFilterBar";
import FeedGrid from "@/components/FeedGrid";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import { Button } from "@/components/ui/button";
import { getFeed } from "@/lib/api";
import { buildPageHref } from "@/lib/pagination";

const LIMIT = 20;
const DESCRIPTION =
  "Competitions and hackathons for students, auto-discovered from public sources and tracked through their registration deadlines.";
const INTRO =
  "Find competitions and hackathons worth entering, and register before their deadlines close.";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Competitions & hackathons",
  description: DESCRIPTION,
  alternates: { canonical: "/competitions" },
};

interface PageProps {
  searchParams: Promise<{
    sort?: string;
    page?: string;
    scope?: string;
    country?: string;
    remote_abroad?: string;
  }>;
}

type CompetitionSort = "recent" | "deadline";
type LocationScope = "abroad" | "domestic" | "both";

const INDIA_COUNTRY_CODE = "IN";

function opportunityCountLabel(count: number): string {
  return `${count} ${count === 1 ? "opportunity" : "opportunities"}`;
}

function parseScope(scope: string | undefined): LocationScope | undefined {
  return scope === "abroad" || scope === "domestic" || scope === "both"
    ? scope
    : undefined;
}

export default async function CompetitionsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const sort: CompetitionSort = params.sort === "recent" ? "recent" : "deadline";
  const scope = parseScope(params.scope);
  const scopedCountry =
    scope === "domestic" || scope === "abroad" ? INDIA_COUNTRY_CODE : undefined;
  const remoteAbroad =
    scope === "domestic" && params.remote_abroad === "true" ? true : undefined;
  const data = await getFeed({
    kind: "competitions",
    scope,
    country: scopedCountry,
    remote_abroad: remoteAbroad,
    sort,
    page,
    limit: LIMIT,
  });
  const totalPages = Math.max(1, Math.ceil(data.total / LIMIT));
  const paginationParams = {
    sort: sort === "recent" ? "recent" : undefined,
    scope,
    country: scopedCountry,
    remote_abroad: remoteAbroad ? "true" : undefined,
  };

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
          items={data.items}
          cols={3}
          skeletonCount={data.items.length || Math.min(LIMIT, 9)}
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
            <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
              {page > 1 ? (
                <Link href={buildPageHref(paginationParams, page - 1, "/competitions")}>
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
                <Link href={buildPageHref(paginationParams, page + 1, "/competitions")}>
                  Next
                </Link>
              ) : (
                "Next"
              )}
            </Button>
          </nav>
        )}
      </FeedNavigationProvider>
    </main>
  );
}
