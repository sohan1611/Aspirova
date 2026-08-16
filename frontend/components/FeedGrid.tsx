"use client";

import { SearchX } from "lucide-react";
import OpportunityCard from "@/components/OpportunityCard";
import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import { Button } from "@/components/ui/button";
import { useFeedNavigation } from "@/components/FeedNavigation";
import type { OpportunityListItem } from "@/lib/types";

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
}

export default function FeedGrid({ items, cols, skeletonCount }: FeedGridProps) {
  const { navigate, isFeedPending } = useFeedNavigation();
  const gridClassName = `grid grid-cols-1 sm:grid-cols-2 gap-6 ${COLS_LG[cols]}`;

  if (isFeedPending) {
    return (
      <div className={gridClassName} aria-busy="true">
        <span className="sr-only" role="status">
          Updating opportunities...
        </span>
        {Array.from({ length: Math.max(1, skeletonCount) }).map((_, index) => (
          <OpportunityCardSkeleton key={index} />
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

  return (
    <div className="flex flex-col items-center px-4 py-20 text-center sm:py-24">
      <div className="rounded-lg border border-border bg-secondary/40 p-3">
        <SearchX className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      </div>
      <h2 className="mt-5 text-xl font-semibold text-foreground">Nothing matches — yet.</h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
        Try a broader search or clear your filters — the almanac updates daily.
      </p>
      <Button className="mt-5" variant="outline" size="sm" onClick={() => navigate("/")}>
        Clear filters
      </Button>
    </div>
  );
}
