import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testModuleLoader } from "../scripts/test-module.mjs";

const component = fn => ({ __esModule: true, default: fn });
const edition = {
  year: 2027, status: "announced", status_label: "Official", basis: "official",
  opens_at: "2027-02-01T00:00:00Z", closes_at: "2027-03-31T00:00:00Z",
  opens_precision: "day", closes_precision: "day", opens_until: null, closes_from: null,
};
function response() {
  return {
    q: "gsoc",
    programmes: { total: 5, items: [{
      entity_type: "programme", slug: "gsoc", name: "Google Summer of Code", organiser: "Google",
      category: "open_source", category_label: "Open source", country: "IN", match: "slug", edition,
      path: "/programme/gsoc", calendar_path: "/calendar?item=gsoc%3A2027%3A0", deadline_rolling: false,
      official_url: "https://summerofcode.withgoogle.com/programs?cycle=2027",
    }] },
    companies: { total: 8, items: [{
      entity_type: "company", slug: "google", name: "Google", domain: "google.com", logo_url: null,
      active_count: 12, match: "exact", path: "/companies/google",
    }] },
  };
}
function view(data = response(), props = {}) {
  const load = testModuleLoader({
    "next/link": component(({ children, ...props }) => React.createElement("a", props, children)),
    "@/components/CompanyFavicon": component(() => React.createElement("span", { "data-logo": true })),
    "@/lib/listingResults": { useSearchRelatedResults: () => data },
  });
  const Component = load("components/SearchBestMatches.tsx").default;
  return renderToStaticMarkup(React.createElement(Component, {
    scope: "/", queryKey: "q=gsoc", q: "gsoc", loading: false,
    ...props,
  }));
}

test("strip labels entities, canonical pages, honest official host and official edition", () => {
  const html = view();
  assert.match(html, /<section aria-labelledby=/);
  assert.match(html, /<h2[^>]*>Best matches/);
  assert.match(html, /Programme · /);
  assert.match(html, /Hiring Calendar/);
  assert.match(html, /href="\/programme\/gsoc"/);
  assert.match(html, /href="\/calendar\?item=gsoc%3A2027%3A0"/);
  assert.match(html, /href="\/companies\/google"/);
  assert.match(html, />Company<\/p>/);
  assert.match(html, /12 open roles/);
  assert.match(html, /Official site ↗ · summerofcode.withgoogle.com/);
  assert.match(html, /href="https:\/\/summerofcode.withgoogle.com\/programs\?cycle=2027" target="_blank" rel="noopener noreferrer"/);
  assert.match(html, /<span class="font-medium">Official<\/span> · Opens 1 Feb 2027 · Deadline 31 Mar 2027/);
  assert.doesNotMatch(html, /aria-live/);
  assert.ok(html.indexOf("Programme ·") < html.indexOf(">Company</p>"));
  assert.match(html, /overflow-x-auto/);
  assert.match(html, /sm:grid/);
});

test("tentative month dates retain historical-trend copy and zero roles are honest", () => {
  const data = response();
  data.programmes.items[0].edition = { ...edition, basis: "tentative", status: "expected", opens_precision: "month", closes_at: null };
  data.companies.items[0].active_count = 0;
  const html = view(data);
  assert.match(html, /<span class="font-medium">Tentative · historical trend<\/span> · Opens Feb 2027/);
  assert.match(html, /No open roles right now/);
});

test("rolling deadlines use the same copy as the home Calendar preview", () => {
  const data = response();
  data.programmes.items[0].deadline_rolling = true;
  const html = view(data);
  assert.match(html, /<span class="font-medium">Official<\/span> · Opens 1 Feb 2027 · Deadline: rolling — apply early/);
  assert.doesNotMatch(html, /Deadline 31 Mar/);
  data.programmes.items[0].edition = null;
  assert.match(view(data), /Dates not announced yet/);
});

test("a company the page already shows as Straight to source is not repeated", () => {
  const html = view(response(), { excludeCompanyNames: [" GOOGLE "] });
  assert.doesNotMatch(html, /href="\/companies\/google"/);
  assert.match(html, /Google Summer of Code/);
  const companyOnly = { ...response(), programmes: { total: 0, items: [] } };
  assert.equal(view(companyOnly, { excludeCompanyNames: ["Google"] }), "");
});

test("no hits, loading and enhancement failures render nothing", () => {
  assert.equal(view(null), "");
  assert.equal(view({ ...response(), programmes: { total: 0, items: [] }, companies: { total: 0, items: [] } }), "");
  assert.equal(view(response(), { loading: true }), "");
});

test("see all programmes links to the Programmes search; listing counts stay with the results", () => {
  const html = view();
  assert.match(html, /href="\/programmes\?q=gsoc"[^>]*>See all 5 programmes/);
  assert.doesNotMatch(html, /See all 8 companies/); // companies page does not read q.
  // The results header shows the total and the Filter panel owns Source; the strip repeats neither.
  assert.doesNotMatch(html, /Listings \(|source=/);
});

test("unsafe official URLs never produce an outbound link", () => {
  const data = response(); data.programmes.items[0].official_url = "javascript:alert(1)";
  assert.doesNotMatch(view(data), /Official site/);
});

const flush = () => new Promise(setImmediate);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function lifecycle() {
  const pending = deferred();
  let now = 0, calls = 0;
  const timers = new Map();
  const load = testModuleLoader({}, {
    Date: { now: () => now },
    setTimeout: (callback, delay) => { const id = Symbol(); timers.set(id, { callback, at: now + delay }); return id; },
    clearTimeout: id => timers.delete(id),
    console: { debug() {} },
  });
  let signal;
  const store = load("lib/searchRelatedStore.ts").createSearchRelatedStore((_q, abort) => { calls++; signal = abort; return pending.promise; });
  return { store, pending, calls: () => calls, signal: () => signal, advance(time) {
    now = time;
    for (const [id, timer] of timers) if (timer.at <= now) { timers.delete(id); timer.callback(); }
  } };
}

test("parallel related response survives remounts, and listings never await it", async () => {
  const { store, pending, calls } = lifecycle();
  store.start("/", "key", "gsoc"); store.start("/", "key", "gsoc");
  assert.equal(calls(), 1);
  assert.equal(store.get("key"), null);
  pending.resolve(response()); await flush();
  store.listingsSettled("key");
  assert.equal(store.get("key").q, "gsoc");
});

test("related may finish after listings within 1.5 s", async () => {
  const { store, pending, advance } = lifecycle();
  store.start("/", "key", "gsoc");
  advance(100); store.listingsSettled("key");
  advance(1400); pending.resolve(response()); await flush();
  assert.equal(store.get("key").q, "gsoc");
});

test("related already ready when slow listings finish is retained", async () => {
  const { store, pending, advance } = lifecycle();
  store.start("/", "key", "gsoc");
  advance(2500); pending.resolve(response()); await flush();
  advance(3000); store.listingsSettled("key");
  assert.equal(store.get("key").q, "gsoc");
});

test("late related response is dropped permanently and aborted", async () => {
  const { store, pending, advance, signal } = lifecycle();
  store.start("/", "key", "gsoc"); store.listingsSettled("key");
  advance(1501); pending.resolve(response()); await flush();
  assert.equal(store.get("key"), null);
  assert.equal(signal().aborted, true);
  store.start("/", "key", "gsoc"); assert.equal(store.get("key"), null);
});

test("failed and superseded enhancements stay hidden", async () => {
  const state = lifecycle();
  state.store.start("/", "old", "gsoc");
  state.pending.reject(new Error("offline")); await flush();
  assert.equal(state.store.get("old"), null);
  const next = lifecycle();
  next.store.start("/", "old", "gsoc");
  next.store.start("/", "new", "");
  next.pending.resolve(response()); await flush();
  assert.equal(next.store.get("old"), null);
});

test("an abandoned listing attempt cannot finish a newer retry's related deadline", async () => {
  const { store, pending, advance } = lifecycle();
  const abandoned = store.start("/", "key", "gsoc");
  const current = store.start("/", "key", "gsoc", true);
  store.listingsSettled("key", abandoned);
  advance(2500); pending.resolve(response()); await flush();
  store.listingsSettled("key", current);
  assert.equal(store.get("key").q, "gsoc");
});

test("listing hook starts the enhancement in parallel and settles listings independently", async () => {
  const listings = deferred(), related = deferred();
  let calls = 0;
  const load = testModuleLoader({
    react: { useCallback: fn => fn, useEffect: fn => fn(), useSyncExternalStore: (_subscribe, snapshot) => snapshot() },
    "@/lib/api": { getSearchRelated: () => { calls++; return related.promise; } },
  });
  const hooks = load("lib/listingResults.ts");
  const render = () => hooks.useListingResults("/", "q=gsoc", true, () => listings.promise, null, "gsoc");
  render(); await flush();
  assert.equal(calls, 1);
  assert.equal(render().settled.status, "loading");
  listings.resolve({ items: [], total: 0 }); await flush();
  assert.equal(render().settled.status, "empty");
  assert.equal(hooks.useSearchRelatedResults("/", "q=gsoc"), null);
  related.resolve(response()); await flush();
  assert.equal(hooks.useSearchRelatedResults("/", "q=gsoc").q, "gsoc");
});

test("getSearchRelated uses an 8 s abortable public no-store read", async () => {
  let request;
  const controller = new AbortController();
  const load = testModuleLoader({}, {
    AbortSignal: { timeout: ms => { assert.equal(ms, 8000); return controller.signal; }, any: signals => { assert.equal(signals[0], controller.signal); return controller.signal; } },
    fetch: async (url, options) => { request = { url, options }; return Response.json(response()); },
  });
  const data = await load("lib/api.ts").getSearchRelated(" gsoc ", controller.signal);
  assert.equal(data.q, "gsoc");
  assert.equal(request.url, "http://127.0.0.1:9999/search/related?q=gsoc");
  assert.equal(request.options.cache, "no-store");
  assert.equal(request.options.headers, undefined);
  assert.equal(request.options.signal, controller.signal);
});
