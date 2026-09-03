"use client";

import ListingSearchInput from "@/components/ListingSearchInput";
import {
  ProgrammesAdvancedFilters,
  type ProgrammesFacetsStatus,
} from "@/components/ProgrammesAdvancedFilters";
import type { Facets } from "@/lib/types";

export default function ProgrammesListingControls({
  facets,
  facetsStatus,
  path,
  activeFilterLabel,
  panelLabel,
  mobileDescription,
  searchPlaceholder,
  searchLabel,
}: {
  facets: Facets | null;
  facetsStatus: ProgrammesFacetsStatus;
  path: "/research" | "/programmes";
  activeFilterLabel: string;
  panelLabel: string;
  mobileDescription: string;
  searchPlaceholder: string;
  searchLabel: string;
}) {
  return (
    <div className="ml-auto flex w-full min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-2 sm:w-auto sm:flex-nowrap">
      <ListingSearchInput
        path={path}
        placeholder={searchPlaceholder}
        ariaLabel={searchLabel}
      />
      <ProgrammesAdvancedFilters
        facets={facets}
        facetsStatus={facetsStatus}
        path={path}
        activeFilterLabel={activeFilterLabel}
        panelLabel={panelLabel}
        mobileDescription={mobileDescription}
      />
    </div>
  );
}
