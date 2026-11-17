import assert from "node:assert/strict";
import { test } from "node:test";
import { testModuleLoader } from "../scripts/test-module.mjs";

const rows = { items: [{ slug: "previous" }], total: 1, loadedAt: 123 };
const empty = { items: [], total: 0, loadedAt: 456 };
const flush = () => new Promise(setImmediate);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function createStore() {
  const timers = new Map();
  let id = 0;
  const load = testModuleLoader({}, {
    setTimeout: callback => { timers.set(++id, callback); return id; },
    clearTimeout: id => timers.delete(id),
  });
  const store = load("lib/listingStore.ts").createListingStore();
  return {
    view(query, fetch, initial = null, scope = "/jobs", retry = false) {
      const key = scope + "?" + query;
      store.load(scope, key, fetch, initial, retry);
      return store.get(key);
    },
    seed: store.seed,
    timeout() { for (const fn of [...timers.values()]) fn(); timers.clear(); },
  };
}

test("successful results and true zero are distinct and do not automatically refetch", async () => {
  for (const [data, status] of [[rows, "results"], [empty, "empty"]]) {
    const store = createStore(); let calls = 0;
    const fetch = async () => { calls++; return data; };
    store.view("q=data", fetch); await flush();
    assert.equal(store.view("q=data", fetch).status, status);
    assert.equal(calls, 1);
  }
});

for (const failure of ["429", "500", "502", "503", "504", "network", "invalid JSON"]) {
  test(failure + " retains results and Retry repeats the same query exactly once", async () => {
    const store = createStore(); let calls = 0;
    const query = "q=data&country=IN&company=A&company=B&page=2";
    const fetch = async () => { if (++calls === 1) throw new Error(failure); return empty; };
    store.view(query, fetch, rows); await flush();
    const failed = store.view(query, fetch);
    assert.equal(failed.status, "failed"); assert.equal(failed.data, rows); assert.equal(failed.loadedAt, 123);
    assert.equal(calls, 1);
    store.view(query, fetch, rows, "/jobs", true);
    store.view(query, fetch, rows, "/jobs", true);
    await flush();
    const success = store.view(query, fetch);
    assert.equal(success.status, "empty"); assert.equal(success.key, "/jobs?" + query); assert.equal(calls, 2);
  });
}

test("a first-load failure has no fabricated data or count", async () => {
  const store = createStore(); const fetch = async () => { throw new Error("offline"); };
  store.view("q=data", fetch); await flush();
  assert.equal(store.view("q=data", fetch).data, null);
});

test("an older failure or success cannot replace newer results or the next stale snapshot", async () => {
  for (const fails of [true, false]) {
    const store = createStore(); const old = deferred();
    const oldFetch = () => old.promise; const newFetch = async () => rows;
    store.view("old", oldFetch); store.view("new", newFetch); await flush();
    if (fails) old.reject(new Error("late failure")); else old.resolve(empty);
    await flush();
    assert.equal(store.view("new", newFetch).data, rows);
    const fail = async () => { throw new Error("offline"); };
    store.view("third", fail); await flush();
    assert.equal(store.view("third", fail).data, rows);
  }
});

test("timeout is failed and a superseded original cannot overwrite Retry", async () => {
  const store = createStore(); const original = deferred(); const retry = deferred(); let calls = 0;
  const fetch = () => ++calls === 1 ? original.promise : retry.promise;
  store.view("slow", fetch, rows); await flush(); store.timeout();
  assert.equal(store.view("slow", fetch).status, "failed");
  assert.equal(store.view("slow", fetch).data, rows);
  store.view("slow", fetch, rows, "/jobs", true); await flush();
  original.resolve(empty); await flush();
  assert.equal(store.view("slow", fetch).status, "loading");
  retry.resolve(rows); await flush();
  assert.equal(store.view("slow", fetch).data, rows); assert.equal(calls, 2);
});

test("a timeout without Retry stays failed even if its abandoned request later succeeds", async () => {
  const store = createStore(); const request = deferred(); const fetch = () => request.promise;
  store.view("slow", fetch); await flush(); store.timeout(); request.resolve(empty); await flush();
  assert.equal(store.view("slow", fetch).status, "failed");
});

test("returning to a superseded in-flight query starts a new request", async () => {
  const store = createStore(); const original = deferred(); let calls = 0;
  const fetch = () => ++calls === 1 ? original.promise : Promise.resolve(rows);
  store.view("A", fetch); await flush();
  store.view("B", async () => empty); await flush();
  store.view("A", fetch); await flush(); original.reject(new Error("late")); await flush();
  assert.equal(store.view("A", fetch).data, rows); assert.equal(calls, 2);
});

test("route scopes are isolated and a seeded default keeps its timestamp", async () => {
  const store = createStore();
  store.seed("/jobs", "/jobs?", rows);
  const fail = async () => { throw new Error("offline"); };
  store.view("data", fail, empty, "/jobs"); store.view("data", fail, null, "/internships"); await flush();
  assert.equal(store.view("data", fail, null, "/jobs").data, rows);
  assert.equal(store.view("data", fail, null, "/internships").data, null);
});
