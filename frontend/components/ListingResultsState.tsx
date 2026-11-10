"use client";

import type { ReactNode } from "react";
import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import { Button } from "@/components/ui/button";
import { getCountry } from "@/lib/countries";
import { parseRoleSignalParams, roleFilterLabel } from "@/lib/roleSignalQuery";
import { getSavedSearchParams, savedSearchSummary } from "@/lib/savedSearchParams";

export function listingEmptyDescription(query: URLSearchParams, description: string): string {
  const { q, country, scope, source, ...params } = getSavedSearchParams(query);
  const filters: string[] = [];
  if (q) filters.push(`search "${q}"`);
  const countryName = getCountry(country)?.name;
  if (countryName) {
    let location = countryName;
    if (scope === "abroad") location = `outside ${countryName}`;
    if (scope === "both") location = `${countryName} and abroad`;
    filters.push(location);
  } else if (scope) {
    const scopes = {
      abroad: "opportunities abroad",
      domestic: "domestic opportunities",
      both: "domestic and overseas opportunities",
    };
    if (scopes[scope]) filters.push(scopes[scope]);
  }
  const summary = savedSearchSummary(params);
  if (summary !== "All opportunities") filters.push(summary);
  const sources = {
    direct: "direct from company",
    unstop: "Unstop",
    remoteok: "RemoteOK",
    devpost: "Devpost",
  };
  if (source && sources[source]) filters.push(sources[source]);
  for (const company of query.getAll("company").filter((value) => value.trim())) {
    filters.push(`company ${company.trim()}`);
  }
  if (query.get("remote_abroad") === "true") filters.push("remote opportunities abroad");
  const top = Number(query.get("top"));
  if (Number.isSafeInteger(top) && top > 0) filters.push(`top ${top} companies`);
  const { posted_within } = parseRoleSignalParams(query);
  if (posted_within !== undefined) {
    filters.push(roleFilterLabel("posted_within", String(posted_within)));
  }
  return filters.length ? `${description} Active filters include ${filters.join(", ")}.` : description;
}

interface ListingResultsStateProps {
  loading: boolean;
  error: string | null;
  retry: () => void;
  retrying?: boolean;
  hasItems: boolean;
  skeletonCount: number;
  cols: number;
  competition?: boolean;
  children: ReactNode;
}

const GRID_COLS: Record<number, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
};

export default function ListingResultsState({
  loading,
  error,
  retry,
  retrying = false,
  hasItems,
  skeletonCount,
  cols,
  competition = false,
  children,
}: ListingResultsStateProps) {
  if ((loading || retrying) && (!retrying || !hasItems)) {
    return (
      <div aria-busy="true">
        <p className="sr-only" role="status" aria-live="polite">
          Loading listings...
        </p>
        <div className={`grid grid-cols-1 gap-6 sm:grid-cols-2 ${GRID_COLS[cols]}`}>
          {Array.from({ length: Math.max(1, skeletonCount) }, (_, index) => (
            <OpportunityCardSkeleton key={index} competition={competition} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      {(error || retrying) && (
        <div
          className="mb-4 rounded-lg border border-border bg-secondary/40 p-4"
          role="status"
          aria-live="polite"
        >
          <p className="text-sm text-foreground">{retrying ? "Retrying listings…" : error}</p>
          {hasItems && (
            <p className="mt-1 text-sm text-muted-foreground">
              Showing previously loaded listings. They may not match your current filters.
            </p>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={retry}
            disabled={retrying}
          >
            {retrying ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}
      {(!error || hasItems) && (
        <div role={!hasItems ? "status" : undefined} aria-live={!hasItems ? "polite" : undefined}>
          {children}
        </div>
      )}
    </>
  );
}
