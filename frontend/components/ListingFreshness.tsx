"use client";

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
  if (days === null || days <= 0) return "· today";
  if (days < 7) return `· ${days}d ago`;
  if (days < 30) return `· ${Math.floor(days / 7)}w ago`;
  if (days < 365) return `· ${Math.floor(days / 30)}mo ago`;
  return `· ${Math.floor(days / 365)}y ago`;
}

export default function ListingFreshness({ postedAt, lastSeenAt, absoluteText }: ListingFreshnessProps) {
  const hydrated = useHydrated();
  const value = postedAt ?? lastSeenAt;

  if (!hydrated) {
    return (
      <span className="tnum text-xs text-muted-foreground">
        <time dateTime={value}>{absoluteText}</time>
      </span>
    );
  }

  const days = ageInDays(value);
  if (postedAt && days !== null && days >= 0 && days < 7) {
    return <Badge className="bg-accent text-accent-foreground">New</Badge>;
  }
  return <span className="tnum text-xs text-muted-foreground">{relativeAge(days)}</span>;
}
