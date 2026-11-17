import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testModuleLoader } from "../scripts/test-module.mjs";

const component = fn => ({ __esModule: true, default: fn });
const link = component(({ children, ...props }) => React.createElement("a", props, children));
const overrides = {
  "next/link": link,
  "@/components/SignedOutHeroVisibility": component(({ children }) => children),
  "@/components/ListingFreshness": component(({ postedAt }) => React.createElement("span", null, postedAt ? "Posted" : "Seen")),
  "@/components/ApplyLink": component(({ slug, children, ...props }) => {
    delete props.variant;
    return React.createElement("a", { ...props, "data-apply": slug }, children);
  }),
};
const load = testModuleLoader(overrides, { URL });
const { closingSoonItems, calendarPreviewItems, DESK_BLOCKS } = load("lib/home.ts");
const Hero = load("components/SignedOutHero.tsx").default;
const Preview = load("components/HomePreviews.tsx").default;
const { HomeDeskView } = load("components/HomeDesk.tsx");
const now = Date.parse("2026-11-18T00:00:00Z");

function role(slug, extra = {}) {
  return {
    slug, title: `Role ${slug}`, category: "job", status: "active", is_hidden: false,
    deadline: "2099-12-01T00:00:00Z", deadline_confidence: "explicit", closed_at: null,
    posted_at: null, last_seen_at: "2026-11-18T00:00:00Z", company: { name: "Example", slug: "example" },
    bookmark_status: "planned", status_date: null, note: null,
    apply_url: "https://boards.greenhouse.io/example/jobs/1",
    destination: { kind: "ats", label: "Greenhouse", host: "boards.greenhouse.io" },
    ...extra,
  };
}

function window(slug, basis, opening, extra = {}) {
  return {
    id: `${slug}:2027:0`, programme: { slug, name: slug },
    edition: { basis, status: basis === "official" ? "announced" : "expected", opens_at: opening, closes_at: "2027-08-01T00:00:00Z", opens_precision: basis === "official" ? "day" : "month", closes_precision: "day", ...extra },
    metadata: { deadline_rolling: false }, is_open_now: false,
  };
}

function emptyDesk() {
  return Object.fromEntries(Array.from(DESK_BLOCKS, key => [key, { items: [], count: 0, reason: key === "matches" ? "no_profile" : "empty" }]));
}

test("server-rendered hero explains sources and verification without requiring signup", () => {
  const html = renderToStaticMarkup(React.createElement(Hero, { closing: [], calendar: [], asOf: now }));
  assert.match(html, /Every opportunity\. One place\./);
  assert.match(html, /company career pages and public listing sites/);
  assert.match(html, /Apply always takes you to the original listing/);
  assert.match(html, /No “verified employer” claim/);
  assert.match(html, /where a link goes and how fresh it is/);
  assert.match(html, /Browse without signing up/);
  assert.match(html, /<form[^>]+role="search"[^>]+action="\/#feed-search"[^>]+method="get"/);
  assert.match(html, /<label for="hero-search"/);
  assert.match(html, /<input(?=[^>]*name="q")(?=[^>]*type="search")(?=[^>]*aria-label="Search opportunities")/);
  for (const category of ["internships", "jobs", "remote", "competitions", "scholarships", "research"]) {
    assert.match(html, new RegExp(`href="/${category}"`));
  }
  assert.match(html, /href="#feed-search"/); // Existing home smoke CTA.
  assert.doesNotMatch(html, /aria-live|role="status"|Create a free account/);
  assert.ok(html.indexOf("hero-search") < html.indexOf("home-closing-title"));
});

test("closing rail filters before capping and orders explicit open deadlines", () => {
  const accepted = Array.from({ length: 8 }, (_, index) => role(`open-${index}`, { deadline: `2027-01-${String(index + 1).padStart(2, "0")}T00:00:00Z` }));
  const rejected = [
    role("estimated", { deadline_confidence: "estimated" }), role("unknown", { deadline_confidence: "unknown" }),
    role("no-date", { deadline: null }), role("past", { deadline: "2020-01-01T00:00:00Z" }),
    role("closed", { closed_at: "2026-11-17T00:00:00Z" }), role("withdrawn", { status: "withdrawn" }),
    role("hidden", { is_hidden: true }), role("flagged", { meta: { safety: { kind: "scam" } } }),
  ];
  assert.deepEqual(Array.from(closingSoonItems([...rejected, ...accepted.reverse()], now), item => item.slug), ["open-0", "open-1", "open-2", "open-3", "open-4", "open-5"]);
  const html = renderToStaticMarkup(React.createElement(Preview, { closing: [...rejected, ...accepted], calendar: [], asOf: now }));
  assert.match(html, /Explicit deadlines from the source/);
  assert.match(html, /<time dateTime="2027-01-01/);
  for (const item of rejected) assert.ok(!html.includes(`Role ${item.slug}`));
});

test("calendar preview prefers official windows, labels tentative trends and deduplicates programmes", () => {
  const tentative = window("Tentative", "tentative", "2026-12-01T00:00:00Z");
  const official = window("Official January", "official", "2027-01-01T00:00:00Z");
  const later = window("Official February", "official", "2027-02-01T00:00:00Z");
  const closed = window("Closed", "official", "2026-11-01T00:00:00Z", { status: "closed" });
  const old = window("Past", "official", "2026-01-01T00:00:00Z", { closes_at: "2026-02-01T00:00:00Z" });
  const items = [tentative, later, official, { ...official, id: "duplicate" }, closed, old];
  assert.deepEqual(Array.from(calendarPreviewItems(items, now), item => item.programme.name), ["Official January", "Official February", "Tentative"]);
  const html = renderToStaticMarkup(React.createElement(Preview, { closing: [], calendar: items, asOf: now }));
  assert.match(html, /Tentative · historical trend/);
  assert.match(html, /href="\/calendar\?item=/);
  assert.ok(html.indexOf(">Official January<") < html.indexOf(">Tentative<"));
});

test("five desk blocks render one next action for each empty state", () => {
  const html = renderToStaticMarkup(React.createElement(HomeDeskView, { data: emptyDesk(), loading: false, error: false, retry() {} }));
  for (const heading of ["New matches", "Next deadlines", "Companies you follow", "Unfinished applications", "Verification warnings"]) assert.ok(html.includes(heading));
  for (const action of ["Set interests", "Open the calendar", "Follow a company", "Find a listing to save", "Review saved listings"]) assert.ok(html.includes(action));
  assert.match(html, /Set interests or add skills/);
  assert.equal((html.match(/h-80 /g) || []).length, 5);
  assert.match(html, /Browse the full feed/);
});

test("desk renders matches, next up, deadlines and safe outbound copy", () => {
  const data = emptyDesk();
  data.matches = { items: [role("match")], count: 1 };
  data.deadlines = { items: [{ kind: "programme", slug: "programme", title: "Programme", deadline: "2027-01-01T00:00:00Z", confidence: "explicit" }], count: 1 };
  data.applications = { items: [role("unfinished", { bookmark_status: "interviewing", status_date: "2026-11-21" })], count: 7 };
  data.warnings = { items: [role("unsafe", { status: "withdrawn", safety: { kind: "scam", note: "Avoid" } })], count: 1 };
  const html = renderToStaticMarkup(React.createElement(HomeDeskView, { data, loading: false, error: false, retry() {} }));
  assert.match(html, /Unfinished applications \(7\)/);
  assert.match(html, /Interview on 21 Nov/);
  assert.match(html, /Explicit deadline/);
  assert.match(html, /Greenhouse/);
  assert.match(html, /Warning: reported as a scam/);
  assert.doesNotMatch(html, /data-apply="unsafe"/);
  assert.match(html, /Seen/);
});

test("home deadlines print the UTC calendar day, as cards and the action center do", () => {
  const { formatDateUtc } = load("lib/date.ts");
  const ref = new Date("2026-11-18T00:00:00Z");
  assert.equal(formatDateUtc("2026-11-19T23:59:59Z", ref), "19 Nov"); // 20 Nov in IST local time.
  assert.equal(formatDateUtc("2027-01-05T00:00:00Z", ref), "5 Jan 2027");
  assert.equal(formatDateUtc("not a date", ref), "not a date");
  const late = `${new Date().getUTCFullYear()}-11-19T23:59:59Z`;
  const preview = renderToStaticMarkup(React.createElement(Preview, { closing: [role("late", { deadline: late })], calendar: [], asOf: now }));
  assert.ok(preview.includes(`<time dateTime="${late}">19 Nov</time>`));
  const data = emptyDesk();
  data.deadlines = { items: [{ kind: "listing", slug: "late", title: "Late", deadline: late, confidence: "explicit" }], count: 1 };
  const desk = renderToStaticMarkup(React.createElement(HomeDeskView, { data, loading: false, error: false, retry() {} }));
  assert.ok(desk.includes(`<time dateTime="${late}">19 Nov</time>`));
});

test("a missing block shows its own failure while populated neighbours remain", () => {
  for (const failed of DESK_BLOCKS) {
    const data = emptyDesk();
    delete data[failed];
    const html = renderToStaticMarkup(React.createElement(HomeDeskView, { data, loading: false, error: false, retry() {} }));
    assert.equal((html.match(/Couldn&#x27;t load/g) || []).length, 1);
    assert.equal((html.match(/<section /g) || []).length, 5);
  }
  const html = renderToStaticMarkup(React.createElement(HomeDeskView, { data: null, loading: false, error: true, retry() {} }));
  assert.equal((html.match(/Try again/g) || []).length, 5);
  assert.match(html, /full feed is below/);
});

test("loading reserves the same five fixed-height blocks as results", () => {
  const html = renderToStaticMarkup(React.createElement(HomeDeskView, { data: null, loading: true, error: false, retry() {} }));
  assert.equal((html.match(/h-80 /g) || []).length, 5);
  assert.equal((html.match(/aria-busy="true"/g) || []).length, 5);
  assert.doesNotMatch(html, /Couldn&#x27;t load|Set interests or add skills/);
});

test("private desk API uses auth, no-store and cancellation; failures stay explicit", async () => {
  let request;
  const api = testModuleLoader({}, { fetch: async (url, options) => {
    request = { url, options };
    return Response.json(emptyDesk());
  } })("lib/api.ts");
  await api.getHomeDesk("test-session", new AbortController().signal);
  assert.match(request.url, /\/home\/desk$/);
  assert.equal(request.options.cache, "no-store");
  assert.equal(request.options.headers.Authorization, "Bearer test-session");
  assert.ok(request.options.signal);
  const failing = testModuleLoader({}, { fetch: async () => new Response(null, { status: 503 }) })("lib/api.ts");
  await assert.rejects(() => failing.getHomeDesk("test-session"), /Couldn't load/);
});

test("preview reads retain the home ISR window and withBuildFallback", () => {
  const source = fs.readFileSync(new URL("../app/(feed)/page.tsx", import.meta.url), "utf8");
  assert.match(source, /export const revalidate = 21600/);
  assert.doesNotMatch(source, /await searchParams|searchParams:/);
  assert.match(source, /withBuildFallback\(\(\) => getFeed\([\s\S]*?deadline_confidence: "explicit"[\s\S]*?PAGE_REVALIDATE/);
  assert.match(source, /withBuildFallback\(\(\) => fetchCalendar\(calendarQuery, undefined, PAGE_REVALIDATE\)/);
  assert.ok(source.indexOf("<HomeActionDesk") < source.indexOf("<FeedResults initialData"));
});
