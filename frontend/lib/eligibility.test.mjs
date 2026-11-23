import assert from "node:assert/strict";
import { test } from "node:test";
import { testModuleLoader } from "../scripts/test-module.mjs";

const load = testModuleLoader({
  "@/lib/api": {
    getFeed: async params => ({ endpoint: "/feed", params }),
    searchOpportunities: async (q, params) => ({ endpoint: "/search", q, params }),
    getForYou: async params => ({ endpoint: "/for-you", params }),
  },
});
const { parseEligibilityParams, appendEligibilityParams, eligibilityLabelText, eligibilityEvidenceText, assertEligibilityFacts } = load("lib/eligibility.ts");
const { parseFeedRequest, loadFeedData } = load("lib/feedQuery.ts");
const { parseOpportunityListingRequest, clearOpportunityListingFilters } = load("lib/opportunityListingQuery.ts");
const { getSavedSearchParams, savedSearchHref } = load("lib/savedSearchParams.ts");
const json = value => JSON.parse(JSON.stringify(value));
const fact = value => ({ value, evidence: "Listing evidence", source: "description" });
const options = { basePath: "/jobs", baseQuery: { category: "job" }, defaultSort: "student", initialPage: 1, limit: 20 };

test("eligibility URL params round trip and reach both APIs", async () => {
  const params = new URLSearchParams("grad_year=2026&stage=undergraduate&stage=postgraduate&eligibility_stated=1");
  const parsed = parseEligibilityParams(params);
  assert.deepEqual(json(parsed), { grad_year: 2026, stage: ["undergraduate", "postgraduate"], eligibility_stated: true });
  const written = new URLSearchParams();
  appendEligibilityParams(written, parsed);
  assert.equal(written.toString(), params.toString());
  for (const q of ["", "&q=developer"]) {
    const request = parseFeedRequest(new URLSearchParams(params.toString() + q));
    assert.equal(request.isCleanDefaultFeed, false);
    assert.equal(request.canReusePrerenderedFeed, false);
    assert.equal(request.isForYou, false);
    const result = await loadFeedData(request);
    assert.equal(result.params.grad_year, 2026);
    assert.deepEqual(json(result.params.stage), ["undergraduate", "postgraduate"]);
    assert.equal(result.params.eligibility_stated, true);
  }
  const listing = parseOpportunityListingRequest(params, options);
  assert.equal(listing.canReusePrerendered, false);
  assert.equal(listing.usesServerPagination, false);
  assert.equal(listing.filters.grad_year, 2026);
  const saved = getSavedSearchParams(params);
  assert.deepEqual(json(saved), json(parsed));
  assert.deepEqual(json(getSavedSearchParams(new URLSearchParams(savedSearchHref(saved).split("?")[1]))), json(parsed));
  clearOpportunityListingFilters(params);
  for (const key of ["grad_year", "stage", "eligibility_stated"]) assert.equal(params.has(key), false);
});

test("eligibility filters override for-you and accept comma stage URLs", () => {
  const request = parseFeedRequest(new URLSearchParams("view=foryou&grad_year=2026&stage=undergraduate,doctoral"));
  assert.equal(request.isForYou, false);
  assert.deepEqual(json(request.filters.stage), ["undergraduate", "doctoral"]);
  assert.equal(parseEligibilityParams(new URLSearchParams("grad_year=2014&stage=bad")).grad_year, undefined);
  assert.equal(parseEligibilityParams(new URLSearchParams("grad_year=2036")).grad_year, undefined);
});

test("compact text describes requirements, and relevant unknown dimensions remain marked", () => {
  const facts = { v: 1, grad_years: fact([2025, 2026]), stages: fact(["undergraduate"]) };
  assert.equal(eligibilityLabelText(facts), "2025-26 batch · Undergraduates");
  assert.equal(eligibilityLabelText({ v: 1, citizenship: fact(["US"]) }), "US citizens only");
  assert.equal(eligibilityLabelText({ v: 1, college_restriction: fact(true) }), "Specific colleges only");
  assert.equal(eligibilityLabelText({ v: 1, final_year_only: fact(true) }), "Final year students only");
  assert.equal(eligibilityLabelText({ v: 1, citizenship: fact([]) }), "Citizenship requirement — country not stated");
  assert.equal(eligibilityLabelText(null), null);
  assert.equal(eligibilityLabelText(null, { grad_year: 2026 }), "Eligibility not stated");
  assert.equal(eligibilityLabelText({ v: 1, grad_years: fact([2026]) }, { stage: ["doctoral"] }), "Eligibility not stated");
  assert.equal(eligibilityLabelText(facts, { grad_year: 2026, stage: ["undergraduate"] }), "2025-26 batch · Undergraduates");
});

test("malformed eligibility payloads are rejected", () => {
  for (const value of [null, undefined, { v: 1 }, { v: 1, citizenship: fact([]) }, { v: 1, grad_years: fact([2026]) }]) assert.doesNotThrow(() => assertEligibilityFacts(value));
  for (const value of [{ v: 2 }, { v: 1, stages: fact(["unknown"]) }, { v: 1, grad_years: fact([]) }, { v: 1, final_year_only: fact(false) }, { v: 1, stages: { ...fact(["school"]), evidence: "x".repeat(161) } }]) assert.throws(() => assertEligibilityFacts(value));
});

test("API feed and search requests serialize the new params", async () => {
  const calls = [];
  const api = testModuleLoader({ "./listingFetch": { fetchListing: async url => { calls.push(url); return { items: [], total: 0 }; } } })("lib/api.ts");
  const params = { grad_year: 2026, stage: ["undergraduate", "doctoral"], eligibility_stated: true };
  await api.getFeed(params);
  await api.searchOpportunities("developer", params);
  for (const url of calls) {
    const query = new URL(url).searchParams;
    assert.equal(query.get("grad_year"), "2026");
    assert.deepEqual(query.getAll("stage"), ["undergraduate", "doctoral"]);
    assert.equal(query.get("eligibility_stated"), "1");
  }
});

test("evidence text quotes each sentence once, in plain words", () => {
  const quote = "Open to final-year undergraduate students graduating in 2026.";
  const facts = {
    v: 1,
    grad_years: { value: [2026], evidence: quote, source: "description" },
    stages: { value: ["undergraduate"], evidence: quote, source: "description" },
    final_year_only: { value: true, evidence: quote, source: "description" },
    citizenship: { value: ["US"], evidence: "US citizens only", source: "tags" },
  };
  assert.equal(
    eligibilityEvidenceText(facts),
    `Listing says “${quote}”; Source tags say “US citizens only” — check all requirements`,
  );
  assert.equal(eligibilityEvidenceText({ v: 1 }), "");
  assert.equal(eligibilityEvidenceText(null), "");
});
