"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { FeedResultData } from "@/lib/feedQuery";
import { createListingStore } from "@/lib/listingStore";

// See listingStore.ts: WHY THIS EXISTS documents the measured Suspense/remount
// failure and why this one-page-load store must stay outside React.
const store = createListingStore<FeedResultData>();
export function useListingResults(scope: string, queryKey: string, enabled: boolean, load: () => Promise<FeedResultData>, initialData: FeedResultData | null) {
  const key = `${scope}?${queryKey}`;
  const getSnapshot = useCallback(() => store.get(key), [key]);
  // SSR has no settled client request: render the supplied prerender, or its
  // explicit unavailable shell when CI/local build had no API.
  const getServerSnapshot = useCallback(() => null, []);
  const settled = useSyncExternalStore(store.subscribe, getSnapshot, getServerSnapshot);
  // load closes over freshly parsed query filters and changes every render.
  // store.load is idempotent per key, so subsequent effects are Map lookups.
  // Keep load in the deps to avoid stale closures or ref writes during render.
  // A default query with successful initialData needs no request; a null offline
  // prerender must fetch on mount even when the URL describes the default view.
  useEffect(() => {
    if (!enabled && initialData && !store.get(key)) store.seed(scope, key, initialData);
    else store.load(scope, key, load, initialData);
  }, [scope, key, enabled, load, initialData]);
  const retry = useCallback(() => store.load(scope, key, load, initialData, true), [scope, key, load, initialData]);
  return { settled, retry };
}
