"use client";

import { ListingEmpty } from "@/components/ListingFeedback";
import OpportunityCard from "@/components/OpportunityCard";
import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import { useFeedNavigation } from "@/components/FeedNavigation";
import type { Facets, OpportunityListItem } from "@/lib/types";

const COLS_LG: Record<number, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
};

interface FeedGridProps {
  items: OpportunityListItem[];
  cols: number;
  skeletonCount: number;
  competitionSkeleton?: boolean;
  emptyFacets?: Facets | null;
  emptyQuery?: string;
  emptyHref?: string;
  emptyActionLabel?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}

export default function FeedGrid({
  items,
  cols,
  skeletonCount,
  competitionSkeleton = false,
  emptyHref = "/",
  emptyQuery = "",
  emptyFacets,
  emptyTitle = "Nothing matches — yet.",
  emptyDescription = "Try a broader search or clear your filters — the almanac updates daily.",
}: FeedGridProps) {
  const { isFeedPending } = useFeedNavigation();
  const gridClassName = `grid grid-cols-1 sm:grid-cols-2 gap-6 ${COLS_LG[cols]}`;

  if (isFeedPending) {
    return (
      <div className={gridClassName} aria-busy="true">
        <span className="sr-only" role="status">
          Updating opportunities...
        </span>
        {Array.from({ length: Math.max(1, skeletonCount) }).map((_, index) => (
          <OpportunityCardSkeleton key={index} competition={competitionSkeleton} />
        ))}
      </div>
    );
  }

  if (items.length > 0) {
    return (
      <div className={gridClassName}>
        {items.map((item) => (
          <OpportunityCard key={item.slug} item={item} />
        ))}
      </div>
    );
  }

  return <ListingEmpty pathname={emptyHref} query={emptyQuery} facets={emptyFacets} title={emptyTitle} description={emptyDescription + " Try dropping the location or search term."} />;
}
