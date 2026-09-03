"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { FeedResultData } from "@/lib/feedQuery";

/**
 * Results store for the listing pages, held outside React and keyed by route
 * plus query string.
 *
 * WHY THIS EXISTS
 *
 * Holding fetched results in component state did not survive. Measured with the
 * only instruments that proved trustworthy here - diagnostics rendered into the
 * DOM, and the API server's own access log - the effect ran, the request went
 * out, the API answered 200 with thousands of rows, and neither .then nor .catch
 * ever reached the rendered component. `settled` stayed null forever, so the
 * grid was blanked and every search showed "Nothing open here" for a query the
 * API had already answered.
 *
 * These pages are statically prerendered and read useSearchParams, so the
 * results subtree ships as a Suspense fallback in the HTML and the client mounts
 * the real component into that boundary. The instance whose effect ran is not
 * the instance being rendered, and state held inside it is lost.
 *
 * The proof is in this same tree: useOpportunityListingFacets fires an identical
 * promise chain and its counts always arrived - because it seeds its state from
 * a module-level cache at mount. Same tree, same fetch shape, different storage.
 *
 * So the results live outside React too, and go one step further than the facets
 * hook: useSyncExternalStore makes React *pull* the current value on every
 * render rather than relying on a setState landing on the right instance. A
 * remount reads the store synchronously, a remount mid-flight attaches to the
 * same promise, and an instance that is merely re-rendered for some other reason
 * picks the data up as well. There is no window where the data exists and the
 * page does not show it.
 *
 * The store lives for one page load, which is the right lifetime: it exists to
 * survive a remount, not to be a data cache.
 */

export interface ListingResultEntry {
  key: string;
  /** `null` records a failed request. A failed fetch must still settle, or the
   *  page shows skeletons forever. */
  data: FeedResultData | null;
}

const MAX_ENTRIES = 30;

const entries = new Map<string, ListingResultEntry>();
const inFlight = new Set<string>();
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function remember(key: string, data: FeedResultData | null) {
  // Bounded so typing in the search box cannot grow this without limit. Map
  // preserves insertion order, so the first key is the oldest.
  if (!entries.has(key) && entries.size >= MAX_ENTRIES) {
    const oldest = entries.keys().next().value;
    if (oldest !== undefined) entries.delete(oldest);
  }
  entries.set(key, { key, data });
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Entries are stored as whole objects so this returns a referentially stable
 * value for an unchanged key - useSyncExternalStore re-renders forever if the
 * snapshot is a fresh object on every call.
 */
function getEntry(key: string): ListingResultEntry | null {
  return entries.get(key) ?? null;
}

function loadOnce(key: string, load: () => Promise<FeedResultData>): void {
  if (entries.has(key) || inFlight.has(key)) return;
  inFlight.add(key);

  void load()
    .then((data) => {
      remember(key, data);
    })
    .catch(() => {
      remember(key, null);
    })
    .finally(() => {
      inFlight.delete(key);
    });
}

/**
 * Resolve the results for one listing view, fetching at most once per view.
 *
 * `scope` is the route the query belongs to. Without it `/jobs?q=data` and
 * `/internships?q=data` share the key `q=data` and one page serves the other's
 * results - they differ only in the base query the caller holds, which never
 * reaches the URL.
 *
 * `enabled` is false when the visitor's query string describes the view that was
 * already prerendered: there is nothing to fetch, and the caller renders the
 * initial data it was handed.
 */
export function useListingResults(
  scope: string,
  queryKey: string,
  enabled: boolean,
  load: () => Promise<FeedResultData>,
): ListingResultEntry | null {
  const key = `${scope}?${queryKey}`;

  const getSnapshot = useCallback(
    () => (enabled ? getEntry(key) : null),
    [key, enabled],
  );
  // The server render is always the prerendered default view, which never has a
  // settled entry.
  const getServerSnapshot = useCallback(() => null, []);

  const settled = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  // `load` closes over the freshly parsed request, so it is a new function every
  // render and this effect re-runs every render. That is fine and deliberate:
  // loadOnce is idempotent per key, so every run after the first is a Map
  // lookup. Keeping `load` in the deps rather than stashing it in a ref avoids
  // both a stale closure and a ref write during render.
  useEffect(() => {
    if (!enabled) return;
    loadOnce(key, load);
  }, [key, enabled, load]);

  return settled;
}
