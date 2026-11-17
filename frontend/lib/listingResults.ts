"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { FeedResultData } from "@/lib/feedQuery";
import { createListingStore } from "@/lib/listingStore";
import { getSearchRelated } from "@/lib/api";
import { createSearchRelatedStore } from "@/lib/searchRelatedStore";

// See listingStore.ts: WHY THIS EXISTS documents the measured Suspense/remount
// failure and why this one-page-load store must stay outside React.
const store = createListingStore<FeedResultData>();
const relatedStore = createSearchRelatedStore(getSearchRelated);

export function useSearchRelatedResults(scope: string, queryKey: string) {
  const key = `${scope}?${queryKey}`;
  const getSnapshot = useCallback(() => relatedStore.get(key), [key]);
  return useSyncExternalStore(relatedStore.subscribe, getSnapshot, () => null);
}

export function useListingResults(scope: string, queryKey: string, enabled: boolean, load: () => Promise<FeedResultData>, initialData: FeedResultData | null, relatedQuery?: string) {
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
    const attempt = relatedStore.start(scope, key, relatedQuery);
    if (!enabled && initialData && !store.get(key)) store.seed(scope, key, initialData);
    else store.load(scope, key, () => load().finally(() => relatedStore.listingsSettled(key, attempt)), initialData);
    if (store.get(key)?.status !== "loading") relatedStore.listingsSettled(key, attempt);
  }, [scope, key, enabled, load, initialData, relatedQuery]);
  const retry = useCallback(() => {
    if (store.get(key)?.retrying) return;
    const attempt = relatedStore.start(scope, key, relatedQuery, true);
    store.load(scope, key, () => load().finally(() => relatedStore.listingsSettled(key, attempt)), initialData, true);
  }, [scope, key, load, initialData, relatedQuery]);
  return { settled, retry };
}
