"use client";

import { useDeferredValue } from "react";
import { Badge } from "@/components/ui/badge";
import { useHydrated } from "@/lib/useHydrated";

const DAY_IN_MS = 24 * 60 * 60 * 1000;

interface ListingFreshnessProps {
  postedAt: string | null;
  lastSeenAt: string;
  absoluteText: string;
}

function ageInDays(value: string): number | null {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return null;
  return Math.floor((Date.now() - timestamp) / DAY_IN_MS);
}

function relativeAge(days: number | null): string {
  if (days === null || days <= 0) return "today";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

export default function ListingFreshness({ postedAt, lastSeenAt, absoluteText }: ListingFreshnessProps) {
  // Deferred: the switch to relative text renders as a low-priority, yielding
  // update instead of joining the hydration task, which kept a long task
  // on phones across twenty cards.
  const hydrated = useDeferredValue(useHydrated(), false);
  const value = postedAt ?? lastSeenAt;
  const label = postedAt ? "Posted" : "Seen";
  const title = postedAt
    ? `Posted on ${absoluteText} by the source`
    : `Last seen on the source ${absoluteText}`;
  const days = hydrated ? ageInDays(value) : null;
  const isNew = postedAt && days !== null && days >= 0 && days < 7;

  return (
    <span className="tnum inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      {isNew && <Badge className="bg-accent text-accent-foreground">New</Badge>}
      <time className="min-w-0 truncate" dateTime={value} title={title}>
        {label} {hydrated && days !== null ? relativeAge(days) : absoluteText}
      </time>
    </span>
  );
}
