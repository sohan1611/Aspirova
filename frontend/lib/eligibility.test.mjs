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
  for (const value of [null, undefined, { v: 1 }, { v: 2 }, { v: 1, citizenship: fact([]) }, { v: 1, grad_years: fact([2026]) }]) assert.doesNotThrow(() => assertEligibilityFacts(value));
  for (const value of [{ v: 0 }, { v: "1" }, { v: 1.5 }, { v: 1, stages: fact(["unknown"]) }, { v: 1, grad_years: fact([]) }, { v: 1, final_year_only: fact(false) }, { v: 1, stages: { ...fact(["school"]), evidence: "x".repeat(161) } }]) assert.throws(() => assertEligibilityFacts(value));
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


const { eligibilityValueText, remoteLabelText } = load("lib/eligibility.ts");
test("DISC-06 card and detail text preserves explicit and unknown restrictions", () => {
  assert.equal(remoteLabelText({ v: 3, remote_regions: fact(["US"]) }, true), "Remote · US only");
  assert.equal(remoteLabelText({ v: 3, remote_regions: fact(["WORLDWIDE"]) }, true), "Remote · Worldwide");
  assert.equal(remoteLabelText({ v: 3, remote_regions: fact(["IN", "PH"]) }, true), "Remote · India, Philippines");
  assert.equal(remoteLabelText({ v: 3, remote_mode: fact("hybrid") }), "Hybrid");
  assert.equal(remoteLabelText({ v: 3 }, true, true), "Remote — where you can work from is not stated");
  assert.equal(remoteLabelText(null, true), "Remote");
  assert.equal(remoteLabelText(null, false, true), null);
  assert.equal(remoteLabelText({ v: 3, remote_mode: fact("onsite") }, true), "On-site");
  assert.equal(remoteLabelText({ v: 3, visa_sponsorship: fact(false), work_authorization: fact(["US"]) }, true), "Remote · No visa sponsorship · US work authorization required");
  for (const [key, value, expected] of [
    ["remote_mode", "remote", "Remote"], ["remote_mode", "hybrid", "Hybrid"], ["remote_mode", "onsite", "On-site"],
    ["remote_regions", ["EMEA", "NORTH_AMERICA", "MIDDLE_EAST"], "EMEA, North America, Middle East"],
    ["remote_regions", ["WORLDWIDE"], "Worldwide"],
    ["work_authorization", [], "Work authorization required — country not stated"],
    ["work_authorization", ["IN"], "IN work authorization required"],
    ["visa_sponsorship", true, "Visa sponsorship available"], ["visa_sponsorship", false, "No visa sponsorship"],
    ["timezones", { min: -5, max: 1 }, "UTC-5 to UTC+1"], ["timezones", { min: 5.5, max: 5.5 }, "UTC+5.5"],
  ]) assert.equal(eligibilityValueText(key, fact(value)), expected);
});

test("DISC-06 facts enforce country, region, boolean and timezone contracts", () => {
  const valid = {
    v: 3, remote_mode: fact("hybrid"),
    remote_regions: { ...fact(["US", "IN", "WORLDWIDE", "EUROPE", "EMEA", "APAC", "ASIA", "LATAM", "NORTH_AMERICA", "MIDDLE_EAST", "AFRICA"]), source: "location" },
    work_authorization: fact([]), visa_sponsorship: fact(false), timezones: fact({ min: -12, max: 14 }),
  };
  assert.doesNotThrow(() => assertEligibilityFacts(valid));
  assert.doesNotThrow(() => assertEligibilityFacts({ ...valid, v: 99 }));
  for (const [key, value] of [
    ["remote_mode", "flexible"], ["remote_mode", true], ["remote_regions", []],
    ["remote_regions", ["REMOTE"]], ["remote_regions", ["ZZ"]], ["remote_regions", ["in"]],
    ["work_authorization", ["WORLDWIDE"]], ["work_authorization", ["ZZ"]],
    ["work_authorization", "US"], ["visa_sponsorship", "false"], ["visa_sponsorship", null],
    ["timezones", { min: -13, max: 1 }], ["timezones", { min: 0, max: 15 }],
    ["timezones", { min: 2, max: 1 }], ["timezones", { min: "1", max: 2 }],
    ["timezones", { min: NaN, max: 1 }], ["timezones", { min: 0, max: Infinity }],
    ["timezones", { min: 1 }], ["timezones", { min: 0, max: 1, other: true }],
  ]) assert.throws(() => assertEligibilityFacts({ v: 3, [key]: fact(value) }), key + " " + JSON.stringify(value));
  assert.throws(() => assertEligibilityFacts({ v: 3, remote_mode: { ...fact("remote"), source: "company" } }));
});

test("visa opt-in round trips through feed, search, listing, saved searches and clear", async () => {
  const sp = new URLSearchParams("visa=needs&country=IN");
  const parsed = parseEligibilityParams(sp);
  assert.equal(parsed.visa, "needs");
  const written = new URLSearchParams();
  appendEligibilityParams(written, parsed);
  assert.equal(written.get("visa"), "needs");
  assert.equal(parseEligibilityParams(new URLSearchParams("visa=true")).visa, undefined);
  for (const query of [sp.toString(), sp.toString() + "&q=developer", sp.toString() + "&view=foryou"]) {
    const request = parseFeedRequest(new URLSearchParams(query));
    assert.equal(request.isCleanDefaultFeed, false);
    assert.equal(request.isForYou, false);
    assert.equal((await loadFeedData(request)).params.visa, "needs");
  }
  const listing = parseOpportunityListingRequest(sp, options);
  assert.equal(listing.filters.visa, "needs");
  assert.equal(listing.canReusePrerendered, false);
  const saved = getSavedSearchParams(sp);
  assert.deepEqual(json(saved), { visa: "needs", country: "IN" });
  assert.deepEqual(json(getSavedSearchParams(new URLSearchParams(savedSearchHref(saved).split("?")[1]))), json(saved));
  clearOpportunityListingFilters(sp);
  assert.equal(sp.has("visa"), false);
  const calls = [];
  const api = testModuleLoader({ "./listingFetch": { fetchListing: async url => { calls.push(url); return { items: [], total: 0 }; } } })("lib/api.ts");
  await api.getFeed({ visa: "needs" });
  await api.searchOpportunities("developer", { visa: "needs" });
  assert.equal(calls.length, 2);
  for (const url of calls) assert.equal(new URL(url).searchParams.get("visa"), "needs");
});

test("remote card evidence is inside the positioned truncating element", async () => {
  const React = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const component = testModuleLoader({ "next/navigation": { useSearchParams: () => new URLSearchParams("scope=domestic&country=IN") } })("components/EligibilityLabel.tsx");
  const html = renderToStaticMarkup(React.createElement(component.RemoteLabel, {
    isRemote: true, facts: { v: 3, remote_regions: { ...fact(["US"]), source: "location" } },
  }));
  assert.match(html, /relative block min-w-0 max-w-full truncate/);
  assert.match(html, /title="Source location says/);
  assert.match(html, /Remote · US only<span class="sr-only">/);
  const unknown = renderToStaticMarkup(React.createElement(component.RemoteLabel, { isRemote: true }));
  assert.match(unknown, /where you can work from is not stated/);
});


test("detail rows render every DISC-06 dimension and preserve Not stated", async () => {
  const React = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { default: EligibilitySection } = load("components/EligibilitySection.tsx");
  const html = renderToStaticMarkup(React.createElement(EligibilitySection, { facts: {
    v: 3, remote_mode: fact("hybrid"), remote_regions: fact(["IN", "PH"]),
    work_authorization: fact(["US"]), visa_sponsorship: fact(false), timezones: fact({ min: -5, max: 1 }),
  } }));
  for (const label of ["Work mode", "Remote from", "Work authorization", "Visa sponsorship", "Time zone"]) assert.ok(html.includes(label));
  for (const value of ["Hybrid", "India, Philippines", "US work authorization required", "No visa sponsorship", "UTC-5 to UTC+1", "“Listing evidence”"]) assert.ok(html.includes(value));
  const unknown = renderToStaticMarkup(React.createElement(EligibilitySection, {}));
  assert.equal(unknown.split("Not stated — check the listing").length - 1, 11);
});


test("remote cards show at most three region values and the remaining count", () => {
  assert.equal(remoteLabelText({ v: 3, remote_regions: fact(["IN", "PH", "CA"]) }, true), "Remote · India, Philippines, Canada");
  assert.equal(remoteLabelText({ v: 3, remote_regions: fact(["IN", "PH", "CA", "US"]) }, true), "Remote · India, Philippines, Canada +1");
  assert.equal(remoteLabelText({ v: 3, remote_regions: fact(["IN", "PH", "CA", "US", "GB"]) }, true), "Remote · India, Philippines, Canada +2");
  assert.equal(eligibilityValueText("remote_regions", fact(["IN", "PH", "CA", "US", "GB"])), "India, Philippines, Canada, US, UK");
});
