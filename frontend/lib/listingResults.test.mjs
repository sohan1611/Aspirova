import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const resolveModule = createRequire(import.meta.url);
const testDirectory = path.dirname(fileURLToPath(import.meta.url));

// Exercise the store without Next, a server, browser fetches or extra packages.
function loadModule(relativePath, overrides = {}, globals = {}) {
  const filename = path.resolve(testDirectory, relativePath);
  const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const loaded = { exports: {} };
  vm.runInNewContext(source, {
    module: loaded,
    exports: loaded.exports,
    require: (name) => overrides[name] ?? resolveModule(name),
    setTimeout,
    clearTimeout,
    ...globals,
  }, { filename });
  return loaded.exports;
}

function createStore() {
  const timers = new Map();
  let timerId = 0;
  let now = 0;
  const store = loadModule("listingResults.ts", {
    react: {
      useCallback: (callback) => callback,
      useEffect: (effect) => effect(),
      useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot(),
    },
  }, {
    // Use the host Error class so simulated API errors pass instanceof Error.
    Error,
    setTimeout: (callback, delay) => {
      const id = ++timerId;
      timers.set(id, { callback, deadline: now + delay });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  return {
    view: (query, load, initialData = { items: [], total: 0 }, scope = "/jobs", enabled = true) =>
      store.useListingResults(scope, query, enabled, load, initialData),
    advance: (milliseconds) => {
      now += milliseconds;
      for (const [id, timer] of Array.from(timers.entries())) {
        if (timer.deadline <= now) {
          timers.delete(id);
          timer.callback();
        }
      }
    },
  };
}

const flush = () => new Promise(setImmediate);
const rows = { items: [{ slug: "previous-listing" }], total: 1 };
const empty = { items: [], total: 0 };

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

test("zero matches settle successfully and repeated renders do not refetch", async () => {
  const store = createStore();
  let calls = 0;
  const load = async () => { calls++; return empty; };
  store.view("q=missing", load);
  assert.equal(store.view("q=missing", load).settled.status, "loading");
  await flush();
  assert.equal(store.view("q=missing", load).settled.status, "success");
  assert.equal(store.view("q=missing", load).settled.data.total, 0);
  assert.equal(calls, 1);
});

for (const failure of ["429", "500", "network", "connection-loss"]) {
  test(`${failure} exposes an error and only explicit Retry repeats the same query`, async () => {
    const store = createStore();
    let calls = 0;
    const query = "q=data&country=IN&experience=early";
    const load = async () => {
      calls++;
      if (calls === 1) throw new Error(`Failed to search: ${failure}`);
      return rows;
    };
    store.view(query, load);
    await flush();
    const failed = store.view(query, load);
    assert.equal(failed.settled.status, "error");
    assert.match(failed.settled.error, failure === "429" ? /Too many requests/ : /Check your connection/);
    store.view(query, load);
    await flush();
    assert.equal(calls, 1);
    failed.retry();
    // Double-clicks and remounts share this same in-flight attempt.
    failed.retry();
    store.view(query, load);
    await flush();
    const retried = store.view(query, load).settled;
    assert.equal(calls, 2);
    assert.equal(retried.key, `/jobs?${query}`);
    assert.equal(retried.status, "success");
    assert.equal(retried.data, rows);
  });
}

test("a failure preserves previously loaded filtered rows", async () => {
  const store = createStore();
  const loadPrevious = async () => rows;
  store.view("q=previous", loadPrevious);
  await flush();
  const loadNext = async () => { throw new Error("offline"); };
  store.view("q=next", loadNext);
  await flush();
  const failed = store.view("q=next", loadNext).settled;
  assert.equal(failed.status, "error");
  assert.equal(failed.data, rows);
});

test("an older query cannot replace newer results or the fallback rows", async () => {
  const store = createStore();
  let resolveOld;
  const loadOld = () => new Promise((resolve) => { resolveOld = resolve; });
  const loadNew = async () => rows;
  store.view("q=old", loadOld);
  store.view("q=new", loadNew);
  await flush();
  resolveOld({ items: [{ slug: "stale-listing" }], total: 1 });
  await flush();
  assert.equal(store.view("q=new", loadNew).settled.data, rows);
  const fail = async () => { throw new Error("offline"); };
  store.view("q=third", fail);
  await flush();
  assert.equal(store.view("q=third", fail).settled.data, rows);
});

test("timeout settles, and its late response cannot overwrite a successful retry", async () => {
  const store = createStore();
  let resolveOld;
  let calls = 0;
  const load = () => {
    calls++;
    return calls === 1 ? new Promise((resolve) => { resolveOld = resolve; }) : Promise.resolve(rows);
  };
  store.view("q=slow", load);
  await flush();
  store.advance(20_000);
  const failed = store.view("q=slow", load);
  assert.equal(failed.settled.status, "error");
  failed.retry();
  await flush();
  resolveOld(empty);
  await flush();
  assert.equal(store.view("q=slow", load).settled.data, rows);
  assert.equal(calls, 2);
});

test("success at 21 seconds replaces the 20-second slow notice without Retry", async () => {
  const store = createStore();
  const attempt = deferred();
  let calls = 0;
  const load = () => { calls++; return attempt.promise; };
  store.view("q=slow", load);
  await flush();
  store.advance(19_999);
  assert.equal(store.view("q=slow", load).settled.status, "loading");
  store.advance(1);
  const slow = store.view("q=slow", load).settled;
  assert.equal(slow.status, "error");
  assert.equal(slow.error, "This is taking longer than usual.");
  store.advance(1_000);
  attempt.resolve(rows);
  await flush();
  const success = store.view("q=slow", load).settled;
  assert.equal(success.status, "success");
  assert.equal(success.data, rows);
  assert.equal(success.error, null);
  assert.equal(calls, 1);
});

test("Retry races a pending original, and the original can win", async () => {
  const store = createStore();
  const original = deferred();
  const retry = deferred();
  let calls = 0;
  const load = () => (++calls === 1 ? original.promise : retry.promise);
  store.view("q=slow", load);
  await flush();
  store.advance(20_000);
  store.view("q=slow", load).retry();
  await flush();
  assert.equal(calls, 2);
  assert.equal(store.view("q=slow", load).settled.retrying, true);
  original.resolve(rows);
  await flush();
  assert.equal(store.view("q=slow", load).settled.status, "success");
  retry.resolve(empty);
  await flush();
  assert.equal(store.view("q=slow", load).settled.data, rows);
});

for (const winner of ["original", "retry"]) {
  test(`a failure after the ${winner} succeeds cannot replace its results`, async () => {
    const store = createStore();
    const original = deferred();
    const retry = deferred();
    let calls = 0;
    const load = () => (++calls === 1 ? original.promise : retry.promise);
    store.view("q=data", load);
    await flush();
    store.advance(20_000);
    store.view("q=data", load).retry();
    await flush();
    const success = winner === "original" ? original : retry;
    const failure = winner === "original" ? retry : original;
    success.resolve(rows);
    await flush();
    failure.reject(new Error("Failed to search: 500"));
    await flush();
    store.advance(30_000);
    const settled = store.view("q=data", load).settled;
    assert.equal(settled.status, "success");
    assert.equal(settled.error, null);
    assert.equal(settled.retrying, false);
    assert.equal(settled.data, rows);
    assert.equal(calls, 2);
  });
}

test("one failed attempt stays loading while another is pending before the timer", async () => {
  const store = createStore();
  const original = deferred();
  const retry = deferred();
  let calls = 0;
  const load = () => (++calls === 1 ? original.promise : retry.promise);
  const view = store.view("q=data", load);
  view.retry();
  await flush();
  original.reject(new Error("offline"));
  await flush();
  const pending = store.view("q=data", load).settled;
  assert.equal(pending.status, "loading");
  assert.equal(pending.error, null);
  store.advance(20_000);
  assert.equal(store.view("q=data", load).settled.error, "This is taking longer than usual.");
  retry.resolve(rows);
  await flush();
  assert.equal(store.view("q=data", load).settled.data, rows);
});

test("all failed attempts expose an actionable error without an automatic retry", async () => {
  const store = createStore();
  const original = deferred();
  const retry = deferred();
  let calls = 0;
  const load = () => (++calls === 1 ? original.promise : retry.promise);
  store.view("q=data", load).retry();
  await flush();
  original.reject(new Error("offline"));
  retry.reject(new Error("Failed to search: 429"));
  await flush();
  const failed = store.view("q=data", load).settled;
  assert.equal(failed.status, "error");
  assert.match(failed.error, /Too many requests/);
  assert.equal(failed.retrying, false);
  store.advance(30_000);
  store.view("q=data", load);
  await flush();
  assert.equal(calls, 2);
});

test("a retry keeps previously loaded rows in the store while pending", async () => {
  const store = createStore();
  const previous = async () => rows;
  store.view("q=previous", previous);
  await flush();
  const retry = deferred();
  let calls = 0;
  const load = () => ++calls === 1 ? Promise.reject(new Error("offline")) : retry.promise;
  store.view("q=next", load);
  await flush();
  store.view("q=next", load).retry();
  await flush();
  const pending = store.view("q=next", load).settled;
  assert.equal(pending.status, "loading");
  assert.equal(pending.retrying, true);
  assert.equal(pending.data, rows);
  retry.resolve(empty);
  await flush();
});

test("route keys are isolated and the default ISR view makes no request", async () => {
  const store = createStore();
  let calls = 0;
  const load = async () => { calls++; return rows; };
  assert.equal(store.view("", load, rows, "/jobs", false).settled, null);
  store.view("q=data", load, rows, "/jobs");
  store.view("q=data", load, empty, "/internships");
  await flush();
  assert.equal(calls, 2);
  assert.equal(store.view("q=data", load, rows, "/jobs").settled.key, "/jobs?q=data");
  assert.equal(store.view("q=data", load, empty, "/internships").settled.key, "/internships?q=data");
});

const countries = loadModule("countries.ts");
const roleSignals = loadModule("roleSignalQuery.ts");
const savedSearchParams = loadModule("savedSearchParams.ts", {
  "./countries": countries,
  "./roleSignalQuery": roleSignals,
});
const states = loadModule("../components/ListingResultsState.tsx", {
  "@/lib/countries": countries,
  "@/lib/roleSignalQuery": roleSignals,
  "@/lib/savedSearchParams": savedSearchParams,
  "@/components/OpportunityCardSkeleton": {
    default: () => React.createElement("div", { "data-skeleton": true }),
  },
  "@/components/ui/button": {
    Button: ({ children, ...props }) => React.createElement("button", props, children),
  },
});

function renderState({ children = "Nothing matches", ...props }) {
  return renderToStaticMarkup(React.createElement(states.default, {
    loading: false, error: null, retry: () => {}, hasItems: false,
    skeletonCount: 3, cols: 3, ...props,
  }, children));
}

test("loading renders skeletons and failures suppress the zero-matches content", () => {
  const loading = renderState({ loading: true });
  assert.match(loading, /Loading listings/);
  assert.equal((loading.match(/data-skeleton/g) ?? []).length, 3);
  assert.doesNotMatch(loading, /Nothing matches/);
  const failed = renderState({ error: "Check your connection and try again." });
  assert.match(failed, /role="status"/);
  assert.match(failed, /aria-live="polite"/);
  assert.match(failed, /<button[^>]*type="button"[^>]*>Retry<\/button>/);
  assert.doesNotMatch(failed, /Nothing matches/);
});

test("retained listings render below an inline error with a fallback explanation", () => {
  const html = renderState({ error: "Too many requests", hasItems: true, children: "Previous rows" });
  assert.match(html, /Showing previously loaded listings/);
  assert.ok(html.indexOf("Too many requests") < html.indexOf("Previous rows"));
});

test("retrying retains visible rows and disables Retry instead of showing skeletons", () => {
  const html = renderState({ loading: true, retrying: true, hasItems: true, children: "Previous rows" });
  assert.match(html, /Previous rows/);
  assert.match(html, /role="status"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Retrying…<\/button>/);
  assert.doesNotMatch(html, /data-skeleton/);
  const firstLoad = renderState({ loading: true, hasItems: true, children: "Fallback rows" });
  assert.match(firstLoad, /data-skeleton/);
  assert.doesNotMatch(firstLoad, /Fallback rows/);
});

test("zero-match copy names selected filters and the empty state is announced", () => {
  const description = states.listingEmptyDescription(
    new URLSearchParams("q=data&company=Acme&location=Delhi&experience=early&page=2"),
    "Try a broader search or clear your filters.",
  );
  assert.match(description, /search "data"/);
  assert.match(description, /company Acme/);
  assert.match(description, /Delhi/);
  assert.match(description, /early career/);
  assert.doesNotMatch(description, / = |experience/);
  assert.doesNotMatch(description, /page/);
  assert.match(renderState({ children: description }), /role="status" aria-live="polite"/);
});

test("filter descriptions use country names and skip view-only and unknown keys", () => {
  const description = states.listingEmptyDescription(new URLSearchParams(
    "q=data&country=IN&experience=early&remote_abroad=true&page=2&cols=4&rows=5&sort=recent&view=foryou&prefer_country=US",
  ), "Try a broader search.");
  assert.match(description, /search "data", India, early career, remote opportunities abroad/);
  assert.doesNotMatch(description, /\bIN\b|true|remote_abroad|experience|early,|page|cols|rows|sort|view|prefer_country|US/);
  assert.equal(states.listingEmptyDescription(
    new URLSearchParams("page=2&cols=4&rows=5&sort=recent&view=foryou&prefer_country=US&unknown=true"),
    "Try a broader search.",
  ), "Try a broader search.");
  assert.equal(states.listingEmptyDescription(
    new URLSearchParams("part_time=false&job_offer=false&experience=unknown&country=ZZ"),
    "Try a broader search.",
  ), "Try a broader search.");
});
