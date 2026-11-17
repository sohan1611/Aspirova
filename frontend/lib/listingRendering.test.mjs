import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testModuleLoader } from "../scripts/test-module.mjs";

const component = fn => ({ __esModule: true, default: fn });
const hidden = component(() => null);
const container = ({ children }) => React.createElement("div", null, children);
const Button = ({ children, asChild, ...props }) => asChild ? React.cloneElement(children, props) : React.createElement("button", { type: "button", ...props }, children);
const empty = { items: [], total: 0, loadedAt: 123 };
let query = new URLSearchParams();
let settled = null;
const overrides = {
  "next/link": component(({ children, ...props }) => React.createElement("a", props, children)),
  "next/navigation": { useSearchParams: () => query, useRouter: () => ({ refresh() {} }) },
  "@/components/ui/button": { Button },
  "@/components/FeedNavigation": { FeedNavigationProvider: container, useFeedNavigation: () => ({ isFeedPending: false }) },
  "@/lib/listingResults": { useListingResults: () => ({ settled, retry() {} }), useSearchRelatedResults: () => null },
  "@/lib/feedPreference": { useFeedCountry: () => "IN", usePreferredCountry: () => null },
  "@/components/OpportunityCard": component(({ item }) => React.createElement("article", null, item.title)),
  "@/components/OpportunityCardSkeleton": component(() => React.createElement("div", { "data-skeleton": true })),
  "@/lib/externalCompanies": { findExternalCompany: () => undefined },
};
for (const name of ["FeedCountryPreference", "FeedViewControls", "ForYouControl", "MostViewed", "PersonalisePrompt", "SearchFilters", "SourceCompanyCard", "TopCompanies", "RecentlyViewed", "HomeDesk", "SignedOutHero", "StatsBar"]) overrides["@/components/" + name] = hidden;

function renderer(fetch = async () => { throw new Error("Unexpected API request"); }, globals = {}) {
  const load = testModuleLoader(overrides, { fetch, ...globals });
  return { load, render: () => renderToStaticMarkup(React.createElement(load("components/FeedResults.tsx").default, { initialData: empty, trendingItems: [] })) };
}

for (const label of ["main feed", "search"]) {
  for (const status of [429, 500, 502, 503, 504, "network", "invalid JSON"]) {
    test(label + " failure " + status + " never renders zero copy or a zero count", () => {
      query = new URLSearchParams(label === "search" ? "q=data&location=Delhi&company=A&company=B" : "country=IN");
      settled = { status: "failed", data: empty, loadedAt: null, error: String(status), retrying: false };
      const html = renderer().render();
      assert.match(html, /Couldn&#x27;t load results/);
      assert.match(html, /Retry/);
      assert.doesNotMatch(html, /0 opportunities|0 jobs|0 results|Nothing matches|No opportunities match|Clear all filters/);
      assert.match(html, /aria-live="polite"/);
    });
  }
  test(label + " true zero renders broadening suggestions, removable chips and calendar", () => {
    query = new URLSearchParams("q=missing&location=Delhi&company=A&company=B&page=2");
    settled = { status: "empty", data: empty, loadedAt: 123, error: null, retrying: false };
    const html = renderer().render();
    assert.match(html, /0 opportunities/);
    assert.match(html, /Try dropping the location or search term/);
    assert.match(html, /Remove Company: A/);
    assert.match(html, /href="\/\?q=missing&amp;location=Delhi&amp;company=B"/);
    assert.match(html, /Clear all filters/);
    assert.match(html, /href="\/calendar"/);
  });
}

test("stale search retains cards with a time and Retry, while suppressing counts", () => {
  query = new URLSearchParams("q=data&location=Delhi");
  settled = { status: "failed", data: { items: [{ slug: "old", title: "Previous result" }], total: 1 }, loadedAt: Date.now() - 120_000, error: "503", retrying: false };
  const html = renderer().render();
  assert.match(html, /Previous result/);
  assert.match(html, /Showing results from 2 minutes ago/);
  assert.match(html, /These results are stale/);
  assert.doesNotMatch(html, /0 opportunities|Nothing matches/);
});

test("failed refresh of a previous zero shows only failure, never the old empty copy", () => {
  query = new URLSearchParams("q=data");
  settled = { status: "failed", data: empty, loadedAt: 123, error: "503", retrying: false };
  assert.doesNotMatch(renderer().render(), /Nothing matches|0 opportunities|Clear all filters/);
});

for (const failure of ["503", "network", "invalid JSON"]) {
  test("SSR main feed throws " + failure + " before any zero-results HTML exists", async () => {
    const { load } = renderer(async url => {
      if (url.includes("/feed?")) {
        if (failure === "network") throw new Error("offline");
        return new Response(failure === "503" ? "unavailable" : "bad JSON", { status: failure === "503" ? 503 : 200 });
      }
      return new Response("unavailable", { status: 503 });
    });
    await assert.rejects(load("app/(feed)/page.tsx").default());
  });
}

test("SSR main feed true zero renders suggestions and calendar", async () => {
  query = new URLSearchParams(); settled = null;
  const { load } = renderer(async url => {
    if (url.includes("/calendar?")) return Response.json({ items: [], rolling: [], months: [], from: "2026-11-18", to: "2027-11-17" });
    if (url.endsWith("/stats")) return Response.json({ opportunities: 0 });
    return Response.json(empty);
  });
  const html = renderToStaticMarkup(await load("app/(feed)/page.tsx").default());
  assert.match(html, /0 (?:opportunities|open jobs)/);
  assert.match(html, /Clear all filters/);
  assert.match(html, /\/calendar/);
});

test("validated cache never stores a malformed 200 or 503 as a successful list", async () => {
  const cache = new Map(); let response = new Response("bad JSON", { status: 200 }); let calls = 0;
  const load = testModuleLoader({ "next/cache": { unstable_cache: (fn, key) => async () => {
    const id = JSON.stringify(key);
    if (cache.has(id)) return cache.get(id);
    const value = await fn(); cache.set(id, value); return value;
  } } }, { fetch: async () => { calls++; return response; } });
  const fetchListing = load("lib/listingFetch.ts").fetchListing;
  await assert.rejects(fetchListing("http://example.test/feed"));
  assert.equal(cache.size, 0);
  response = new Response("unavailable", { status: 503 });
  await assert.rejects(fetchListing("http://example.test/feed"));
  assert.equal(cache.size, 0);
  response = Response.json(empty);
  assert.equal((await fetchListing("http://example.test/feed")).total, 0);
  assert.equal(cache.size, 1); assert.equal(calls, 3);
});

for (const failure of [503, "network", "invalid JSON"]) {
  test("search fetch " + failure + " propagates into a rendered failure with the original query", async () => {
    query = new URLSearchParams("q=data&company=A&company=B&location=Delhi&page=2");
    let requested;
    const { load, render } = renderer(async url => {
      requested = new URL(url);
      if (failure === "network") throw new Error("offline");
      return new Response("unavailable", { status: failure === 503 ? 503 : 200 });
    });
    const { parseFeedRequest, loadFeedData } = load("lib/feedQuery.ts");
    const store = load("lib/listingStore.ts").createListingStore();
    const key = "/?" + query;
    store.load("/", key, () => loadFeedData(parseFeedRequest(query)), empty);
    await new Promise(setImmediate);
    settled = store.get(key);
    assert.equal(settled.status, "failed");
    assert.equal(requested.pathname, "/search");
    assert.deepEqual(requested.searchParams.getAll("company"), ["A", "B"]);
    assert.equal(requested.searchParams.get("page"), "2");
    assert.match(render(), /Retry/);
    assert.doesNotMatch(render(), /0 opportunities|Nothing matches|Clear all filters/);
  });
}

test("expired validated snapshots await the next fetch and throw on failure", async () => {
  let now = 10_000;
  class Clock extends Date { static now() { return now; } }
  const cache = new Map(); let calls = 0;
  const load = testModuleLoader({ "next/cache": { unstable_cache: (fn, key) => async () => {
    const id = JSON.stringify(key);
    if (cache.has(id)) return cache.get(id);
    const result = await fn(); cache.set(id, result); return result;
  } } }, { Date: Clock, fetch: async () => ++calls === 1 ? Response.json(empty) : new Response("unavailable", { status: 503 }) });
  const fetchListing = load("lib/listingFetch.ts").fetchListing;
  assert.equal((await fetchListing("http://example.test/feed", 300)).loadedAt, 10_000);
  now = 300_000;
  await assert.rejects(fetchListing("http://example.test/feed", 300), /503/);
  assert.equal(calls, 2);
  assert.equal(cache.size, 1);
});

test("empty descriptions retain human filter labels without presentation parameters", () => {
  const states = renderer().load("components/ListingResultsState.tsx");
  const description = states.listingEmptyDescription(new URLSearchParams("q=data&company=Acme&location=Delhi&experience=early&country=IN&page=2&cols=4"), "Try a broader search.");
  assert.match(description, /search "data"/);
  assert.match(description, /company Acme/);
  assert.match(description, /Delhi/);
  assert.match(description, /early career/);
  assert.match(description, /India/);
  assert.doesNotMatch(description, /page|cols|experience|\bIN\b/);
});

test("failed calendar facets leave filter buttons usable and omit counts", () => {
  const load = testModuleLoader({ ...overrides,
    "@/components/CountedAdvancedFilterShell": { CountedAdvancedFilterShell: () => null },
  });
  const calendar = load("lib/hiringCalendar.ts");
  const html = renderToStaticMarkup(React.createElement(load("components/calendar/Filters.tsx").default, {
    query: calendar.parseCalendarParams(new URLSearchParams(), "2026-11-17"),
    search: "", onSearch() {}, items: [], today: "2026-11-17", onChange() {}, onClear() {}, countsKnown: false,
  }));
  assert.match(html, /Research/);
  assert.doesNotMatch(html, /disabled|>0<|\(0\)/);
});

test("expired ISR snapshots show only relative time and Retry", () => {
  const Notice = renderer().load("components/ListingFeedback.tsx").ListingSnapshotNotice;
  const html = renderToStaticMarkup(React.createElement(Notice, { loadedAt: Date.now() - 120_000, expiresAt: Date.now() - 60_000 }));
  assert.match(html, /These results were last updated/);
  assert.match(html, /couldn&#x27;t be refreshed/);
  assert.doesNotMatch(html, /UTC|Cached snapshot|Refresh/);
  assert.match(html, /2 minutes ago/);
  assert.match(html, /<time dateTime=/);
  assert.match(html, /Retry/);
});

test("fresh ISR snapshots and snapshots without an expiry render nothing", () => {
  const Notice = renderer().load("components/ListingFeedback.tsx").ListingSnapshotNotice;
  for (const expiresAt of [undefined, Date.now() + 60_000]) {
    assert.equal(renderToStaticMarkup(React.createElement(Notice, { loadedAt: Date.now(), expiresAt })), "");
  }
});

test("the expiry boundary shows a Retry that calls router.refresh", () => {
  class Clock extends Date { static now() { return 120_000; } }
  let retry; let refreshes = 0;
  const load = testModuleLoader({ ...overrides,
    "next/navigation": { useRouter: () => ({ refresh() { refreshes++; } }) },
    "@/components/ui/button": { Button: props => { retry = props.onClick; return Button(props); } },
  }, { Date: Clock });
  const Notice = load("components/ListingFeedback.tsx").ListingSnapshotNotice;
  assert.match(renderToStaticMarkup(React.createElement(Notice, { loadedAt: 60_000, expiresAt: 120_000 })), /1 minute ago/);
  retry();
  assert.equal(refreshes, 1);
});

test("an offline CI/local feed prerender renders failure rather than zero", async () => {
  query = new URLSearchParams(); settled = null;
  const { load } = renderer(async () => { throw new Error("offline"); }, {
    process: { env: { NEXT_PHASE: "phase-production-build", NEXT_PUBLIC_API_URL: "http://localhost:8000" } },
  });
  const html = renderToStaticMarkup(await load("app/(feed)/page.tsx").default());
  assert.match(html, /Couldn&#x27;t load results/);
  assert.doesNotMatch(html, /0 opportunities|0 jobs|0 results|Nothing matches|Clear all filters/);
});
