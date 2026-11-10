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
  status: "loading" | "success" | "error";
  data: FeedResultData | null;
  error: string | null;
  retrying: boolean;
}

const MAX_ENTRIES = 30;
const REQUEST_TIMEOUT_MS = 20_000;

interface ListingRequestGroup {
  attempts: Map<symbol, ReturnType<typeof setTimeout>>;
  slow: boolean;
}

const entries = new Map<string, ListingResultEntry>();
const inFlight = new Map<string, ListingRequestGroup>();
const latestKeyByScope = new Map<string, string>();
const lastDataByScope = new Map<string, FeedResultData>();
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function remember(entry: ListingResultEntry) {
  // Bounded so typing in the search box cannot grow this without limit. Map
  // preserves insertion order, so the first key is the oldest.
  if (!entries.has(entry.key) && entries.size >= MAX_ENTRIES) {
    const oldest = entries.keys().next().value;
    if (oldest !== undefined) entries.delete(oldest);
  }
  entries.set(entry.key, entry);
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

function loadOnce(
  scope: string,
  key: string,
  load: () => Promise<FeedResultData>,
  retry = false,
): void {
  latestKeyByScope.set(scope, key);
  const existing = entries.get(key);
  if (!retry && existing) {
    if (existing.status === "success" && existing.data) lastDataByScope.set(scope, existing.data);
    return;
  }
  // Ignore double-clicks while a retry is loading and callbacks from an error
  // notice whose pending original request has already succeeded.
  if (retry && (existing?.retrying || existing?.status === "success")) return;
  if (!retry && inFlight.has(key)) return;
  const requests: ListingRequestGroup = inFlight.get(key) ?? {
    attempts: new Map(),
    slow: false,
  };
  const token = Symbol(key);
  inFlight.set(key, requests);
  const previousData = entries.get(key)?.data ?? lastDataByScope.get(scope) ?? null;
  remember({ key, status: "loading", data: previousData, error: null, retrying: retry });

  function discardGroup() {
    for (const timer of requests.attempts.values()) clearTimeout(timer);
    inFlight.delete(key);
  }

  function isCurrentGroup(): boolean {
    if (inFlight.get(key) !== requests) return false;
    if (latestKeyByScope.get(scope) === key) return true;
    discardGroup();
    entries.delete(key);
    return false;
  }

  function finish(data: FeedResultData | null, error: string | null) {
    if (!isCurrentGroup()) return;
    clearTimeout(timeout);
    requests.attempts.delete(token);
    if (data) {
      // The first success wins, including an original request arriving after
      // its slow notice or during Retry. Later completions cannot replace it.
      discardGroup();
      lastDataByScope.set(scope, data);
      remember({ key, status: "success", data, error: null, retrying: false });
      return;
    }
    if (requests.attempts.size > 0 && !requests.slow) return;
    if (requests.attempts.size === 0) discardGroup();
    remember({
      key,
      status: "error",
      data: previousData,
      error: requests.attempts.size > 0 ? slowMessage : error,
      retrying: false,
    });
  }

  const failureMessage = "We couldn't load listings. Check your connection and try again.";
  const slowMessage = "This is taking longer than usual.";
  const timeout = setTimeout(() => {
    if (!isCurrentGroup()) return;
    requests.slow = true;
    remember({ key, status: "error", data: previousData, error: slowMessage, retrying: false });
  }, REQUEST_TIMEOUT_MS);
  requests.attempts.set(token, timeout);
  void Promise.resolve()
    .then(load)
    .then(
      (data) => finish(data, null),
      (error: unknown) => {
        // The existing API helpers report HTTP status in the Error message.
        const rateLimited = error instanceof Error && /\b429\b/.test(error.message);
        finish(
          null,
          rateLimited ? "Too many requests, wait a moment and retry." : failureMessage,
        );
      },
    );
}

/**
 * Resolve one listing view, fetching once unless the visitor explicitly retries.
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
  initialData: FeedResultData,
): { settled: ListingResultEntry | null; retry: () => void } {
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
    if (!enabled) {
      latestKeyByScope.set(scope, key);
      lastDataByScope.set(scope, initialData);
      return;
    }
    loadOnce(scope, key, load);
  }, [scope, key, enabled, load, initialData]);

  const retry = useCallback(() => {
    if (enabled) loadOnce(scope, key, load, true);
  }, [scope, key, enabled, load]);

  return { settled, retry };
}
