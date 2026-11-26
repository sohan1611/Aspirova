"use client";

import { useDeferredValue } from "react";
import { freshnessText, relativeFreshnessText, type FreshnessData } from "@/lib/freshness";
import { useHydrated } from "@/lib/useHydrated";

export default function FreshnessLabel({ item }: { item: FreshnessData }) {
  const hydrated = useDeferredValue(useHydrated(), false);
  const text = hydrated ? relativeFreshnessText(item) : freshnessText(item);
  if (!text) return null;
  return <p className="min-w-0 max-w-full text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]"
    title="Last seen in a source crawl or confirmed by a successful destination check. This does not verify eligibility.">
    {text}
  </p>;
}
