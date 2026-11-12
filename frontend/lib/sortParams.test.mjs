// Run with node --test lib/sortParams.test.mjs (Node 23.6+ strips TS types).
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test } from "node:test";
import { parseSortParams, sortApiParams, writeSortParams } from "./sortParams.ts";

const apiStub = "data:text/javascript," + encodeURIComponent(`
  export async function getFeed(params) { return { endpoint: '/feed', params }; }
  export async function searchOpportunities(q, params) { return { endpoint: '/search', q, params }; }
  export async function getForYou(params) { return { endpoint: '/for-you', params }; }
`);

// Exercise request parsing and forwarding with API calls stubbed at the module boundary.
const hooks = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@/lib/api") return nextResolve(apiStub, context);
    if (specifier.startsWith("@/lib/")) {
      return nextResolve(new URL(`./${specifier.slice(6)}.ts`, import.meta.url).href, context);
    }
    if (specifier.startsWith("./") && !/\.[a-z]+$/i.test(specifier) &&
        context.parentURL?.startsWith(new URL("./", import.meta.url).href)) {
      return nextResolve(new URL(`${specifier}.ts`, context.parentURL).href, context);
    }
    return nextResolve(specifier, context);
  },
});
const { parseFeedRequest, loadFeedData } = await import("./feedQuery.ts");
const { parseOpportunityListingRequest, loadOpportunityListingData, clearOpportunityListingFilters } =
  await import("./opportunityListingQuery.ts");
const { getSavedSearchParams } = await import("./savedSearchParams.ts");
hooks.deregister();

const listingOptions = {
  basePath: "/jobs", baseQuery: { category: "job" }, defaultSort: "student", initialPage: 1, limit: 20,
};

const cases = [
  ["", "newest", true, { sort: "student" }],
  ["students=0", "newest", false, { sort: "recent" }],
  ["sort=pay", "pay", true, { sort: "pay", students: true }],
  ["sort=pay&students=0", "pay", false, { sort: "pay" }],
  ["sort=deadline", "deadline", true, { sort: "deadline", students: true }],
  ["sort=deadline&students=0", "deadline", false, { sort: "deadline" }],
  ["sort=recent", "newest", true, { sort: "student" }],
  ["sort=student", "newest", true, { sort: "student" }],
  ["sort=junk", "newest", true, { sort: "student" }],
  ["sort=prize", "newest", true, { sort: "student" }],
  ["students=false", "newest", true, { sort: "student" }],
];

for (const [query, uiSort, forStudents, api] of cases) {
  test(`URL state and API mapping for ${query || "no params"}`, () => {
    const params = new URLSearchParams(query);
    assert.deepEqual(parseSortParams(params), { uiSort, forStudents, ...api });
    assert.deepEqual(sortApiParams(uiSort, forStudents), api);
    for (const request of [parseFeedRequest(params), parseOpportunityListingRequest(params, listingOptions)]) {
      assert.equal(request.uiSort, uiSort);
      assert.equal(request.forStudents, forStudents);
      assert.equal(request.sort, api.sort);
      assert.equal(request.students, api.students);
    }
    const feed = parseFeedRequest(params);
    assert.equal(feed.isCleanDefaultFeed, query === "");
    assert.equal(feed.canReusePrerenderedFeed, query === "");
    if (uiSort !== "newest" || !forStudents) {
      const listing = parseOpportunityListingRequest(params, listingOptions);
      assert.equal(listing.canReusePrerendered, false);
      assert.equal(listing.usesServerPagination, false);
    }
  });
}

test("writing Newest + ON removes both presentation params and retains filters", () => {
  const params = new URLSearchParams("sort=pay&students=0&role=software");
  writeSortParams(params, "newest", true);
  assert.equal(params.toString(), "role=software");
});

test("every state round trips through canonical URL params", () => {
  for (const uiSort of ["newest", "deadline", "pay"]) {
    for (const forStudents of [true, false]) {
      const params = new URLSearchParams();
      writeSortParams(params, uiSort, forStudents);
      assert.deepEqual(parseSortParams(params), { uiSort, forStudents, ...sortApiParams(uiSort, forStudents) });
      assert.equal(params.has("sort"), uiSort !== "newest");
      assert.equal(params.has("students"), !forStudents);
    }
  }
});

test("prerender reuse still respects filters, page, and grid size", () => {
  for (const query of ["q=engineer", "role=data", "page=2", "cols=4", "rows=5"]) {
    assert.equal(parseFeedRequest(new URLSearchParams(query)).canReusePrerenderedFeed, false);
  }
  const request = parseOpportunityListingRequest(new URLSearchParams("students=0"), {
    ...listingOptions, initialPage: 3,
  });
  assert.equal(request.page, 1);
  assert.equal(request.canReusePrerendered, false);
});

test("clear all resets sort and student toggle and saved searches exclude both", () => {
  const params = new URLSearchParams("sort=pay&students=0&role=software&q=engineer");
  assert.deepEqual(getSavedSearchParams(params), { q: "engineer", role: "software" });
  clearOpportunityListingFilters(params);
  assert.equal(params.toString(), "q=engineer");
});

test("homepage and listing loads pass mapped ordering through feed and search", async () => {
  for (const [query, , , api] of cases) {
    for (const search of [false, true]) {
      const params = new URLSearchParams(query);
      if (search) params.set("q", "engineer");
      const results = [
        await loadFeedData(parseFeedRequest(params)),
        await loadOpportunityListingData(parseOpportunityListingRequest(params, listingOptions)),
      ];
      for (const result of results) {
        assert.equal(result.endpoint, search ? "/search" : "/feed");
        assert.equal(result.params.sort, api.sort);
        assert.equal(result.params.students, api.students);
      }
    }
  }
  const result = await loadFeedData(parseFeedRequest(new URLSearchParams()));
  assert.equal(result.params.sort, "student");
  assert.equal(result.params.students, undefined);
  assert.equal(result.params.prefer_logos, true);
});
