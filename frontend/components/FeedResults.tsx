"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import FeedCountryPreference from "@/components/FeedCountryPreference";
import FeedGrid from "@/components/FeedGrid";
import ListingResultsState, { listingEmptyDescription } from "@/components/ListingResultsState";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import FeedViewControls from "@/components/FeedViewControls";
import ForYouControl from "@/components/ForYouControl";
import MostViewed from "@/components/MostViewed";
import PersonalisePrompt from "@/components/PersonalisePrompt";
import SearchFilters from "@/components/SearchFilters";
import SourceCompanyCard from "@/components/SourceCompanyCard";
import TopCompanies from "@/components/TopCompanies";
import { Button } from "@/components/ui/button";
import { useFeedCountry, usePreferredCountry } from "@/lib/feedPreference";
import { findExternalCompany } from "@/lib/externalCompanies";
import { type FeedResultData, loadFeedData, parseFeedRequest } from "@/lib/feedQuery";
import { useListingResults } from "@/lib/listingResults";
import { matchesResearchIntent } from "@/lib/programmes";
import type { OpportunityListItem } from "@/lib/types";

interface FeedResultsProps {
  // The statically prerendered clean default feed. Reused as-is whenever the
  // visitor's query string describes that same view, which is the overwhelming
  // majority of traffic - that reuse is the entire point of this component.
  initialData: FeedResultData;
  trendingItems: OpportunityListItem[];
}

function pageHref(searchParams: URLSearchParams, page: number): string {
  const next = new URLSearchParams(searchParams.toString());
  next.set("page", String(page));
  return `/?${next.toString()}`;
}

export default function FeedResults({ initialData, trendingItems }: FeedResultsProps) {
  const searchParams = useSearchParams();
  // During the static prerender useSearchParams() yields an empty set, which
  // parses to exactly the default request - so the build renders initialData and
  // the HTML ships with real listings in it.
  const query = new URLSearchParams(searchParams.toString());
  const request = parseFeedRequest(query);

  const countryCode = useFeedCountry();
  const preferredCountry = usePreferredCountry();
  const preferenceApplies =
    !request.q &&
    !request.isForYou &&
    !query.has("scope") &&
    !query.has("country") &&
    request.sort !== "deadline";
  const preference = preferenceApplies ? preferredCountry : null;
  const queryKey = JSON.stringify([query.toString(), preference]);

  // Results are held outside React, keyed by route plus query string - see
  // lib/listingResults.ts for why component state could not hold them on these
  // statically prerendered, useSearchParams-reading routes.
  const { settled, retry } = useListingResults(
    "/",
    queryKey,
    !request.canReusePrerenderedFeed || preference !== null,
    () => loadFeedData({ ...request, prefer_country: preference ?? undefined }),
    initialData,
  );

  // A preference-only fetch keeps the prerendered list visible while it settles.
  const isLoading = !request.canReusePrerenderedFeed && (!settled || settled.status === "loading");
  const data = settled?.data ?? initialData;

  const sourceCompany = request.q ? findExternalCompany(request.q) : undefined;
  const showResearch = request.q ? matchesResearchIntent(request.q) : false;
  const totalPages = Math.max(1, Math.ceil(data.total / request.limit));

  return (
    <>
      {request.isCleanDefaultFeed && <MostViewed items={trendingItems} />}

      <FeedNavigationProvider>
        <div id="feed-search" className="mb-5 scroll-mt-20 pt-5 sm:pt-8">
          <PersonalisePrompt />
          <ForYouControl />
          <div className="mt-3">
            <SearchFilters />
          </div>
        </div>

        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {!request.q && !request.isForYou && typeof data.open_total === "number"
              ? `${data.open_total.toLocaleString("en-IN")} ${request.kind === "roles" ? "open jobs and internships" : "open opportunities"}`
              : `${data.total.toLocaleString("en-IN")} opportunities`}
            {preferenceApplies && (
              <FeedCountryPreference countryCode={countryCode} preferredCountry={preference} />
            )}
          </p>
          <FeedViewControls cols={request.cols} rows={request.rows} />
        </div>

        {sourceCompany && (
          <section className="mb-6 max-w-md">
            <p className="eyebrow mb-3">Straight to source</p>
            <SourceCompanyCard company={sourceCompany} />
          </section>
        )}

        {showResearch && (
          <section className="mb-6 max-w-md">
            <div className="rounded-lg border border-border bg-card p-5 shadow-soft">
              <p className="eyebrow">Research track</p>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                India&apos;s flagship IISc, IIT, NIT &amp; TIFR research fellowships and
                internships, with the windows they usually open in.
              </p>
              <Button asChild variant="outline" size="sm" className="mt-4">
                <Link href="/research">Explore the research track →</Link>
              </Button>
            </div>
          </section>
        )}

        <TopCompanies />

        <ListingResultsState
          loading={isLoading}
          error={settled?.error ?? null}
          retry={retry}
          retrying={settled?.retrying ?? false}
          hasItems={data.items.length > 0}
          skeletonCount={data.items.length || Math.min(request.limit, 9)}
          cols={request.cols}
        >
          <FeedGrid
            items={data.items}
            cols={request.cols}
            skeletonCount={data.items.length || Math.min(request.limit, 9)}
            emptyHref="/"
            emptyActionLabel="Clear filters"
            emptyDescription={listingEmptyDescription(
              query,
              "Try a broader search or clear your filters — the almanac updates daily.",
            )}
          />
        </ListingResultsState>

        {!isLoading && !settled?.error && totalPages > 1 && (
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3 sm:gap-4">
            <Button
              variant="outline"
              size="sm"
              disabled={request.page <= 1}
              asChild={request.page > 1}
            >
              {request.page > 1 ? (
                <Link href={pageHref(query, request.page - 1)}>Previous</Link>
              ) : (
                "Previous"
              )}
            </Button>
            <span className="text-sm text-muted-foreground">
              Page {request.page} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={request.page >= totalPages}
              asChild={request.page < totalPages}
            >
              {request.page < totalPages ? (
                <Link href={pageHref(query, request.page + 1)}>Next</Link>
              ) : (
                "Next"
              )}
            </Button>
          </div>
        )}
      </FeedNavigationProvider>
    </>
  );
}
