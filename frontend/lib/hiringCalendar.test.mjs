// Run with node --test lib/hiringCalendar.test.mjs (Node 23.6+).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addDays, calendarDays, calendarParams, currentCycleYear, monthRange,
  openingInMonth, parseCalendarParams, presetRange, programmeSummaryName, rangeError, shiftMonth, todayIST, validDay, windowText,
  categoryLabel, clampRange, collapseRecurrences, daysUntilDeadline, eventsOnDay, fetchCalendar,
  filterCalendarItems, howToApply, isClosingSoon, keyDatesText, monthPrecisionItems, monthsInRange,
  officialDeadline, periodRange, registrationEvents, registrationMonths, selectOpenNow, stepPeriod, timelineWindow,
} from "./hiringCalendar.ts";

const today = "2026-11-13";

test("compact programme names include the organiser without repeating names or acronyms", () => {
  const cases = [
    ["Summer Student Programme", "CERN", "CERN · Summer Student Programme"],
    ["Young Professional Program and Internship", "SEBI", "SEBI · Young Professional Program and Internship"],
    ["NITI Aayog Internship Scheme", "NITI Aayog", "NITI Aayog Internship Scheme"],
    ["niti aayog Internship Scheme", "NITI Aayog", "niti aayog Internship Scheme"],
    ["RBI Research Internship", "Reserve Bank of India (RBI)", "RBI Research Internship"],
    ["sebi Young Professional Programme", "Securities and Exchange Board of India [SEBI]", "sebi Young Professional Programme"],
    ["Reserve Bank of India Summer Placement", "Reserve Bank of India (RBI)", "Reserve Bank of India Summer Placement"],
    ["SUMMIT research programme", "MIT", "MIT · SUMMIT research programme"],
    ["Summer research", "", "Summer research"],
  ];
  for (const [name, organiser, expected] of cases) {
    assert.equal(programmeSummaryName({ name, organiser }), expected);
  }
});

test("default is a month-by-month list for the next 12 months in IST", () => {
  const query = parseCalendarParams(new URLSearchParams(), today);
  assert.equal(currentCycleYear(today), 2027);
  assert.equal(currentCycleYear("2029-01-01"), 2029);
  assert.equal(query.view, "list");
  assert.equal(query.period, "next12");
  assert.equal(query.from, today);
  assert.equal(query.to, "2027-11-12");
});

test("URL round trip preserves range, categories, status and query", () => {
  for (const view of ["year", "month", "days", "custom"]) {
    const query = parseCalendarParams(new URLSearchParams({ view, year: "2028", month: "2028-02", days: "90" }), today);
    query.category = ["early_career", "government_internship"];
    query.status = "expected";
    query.q = "IIT & research";
    query.item = "niti-aayog-internship:2028:3";
    query.closingSoon = true;
    query.officialOnly = true;
    assert.deepEqual(parseCalendarParams(calendarParams(query), today), query);
    const api = calendarParams(query, true);
    assert.equal(api.has("view"), false);
    assert.deepEqual(api.getAll("category"), query.category);
  }
});

test("invalid params safely return canonical ranges", () => {
  const query = parseCalendarParams(new URLSearchParams("view=custom&from=2027-02-30&to=2030-02-01&category=junk&status=junk"), today);
  assert.equal(query.from, today);
  assert.deepEqual(query.category, ["junk"]);
  assert.equal(query.status, "");
  assert.equal(validDay("2027-02-29"), false);
  assert.equal(validDay("2028-02-29"), true);
  assert.ok(rangeError("2027-03-01", "2027-02-01"));
  assert.ok(rangeError("2027-01-01", "2029-01-02"));
  assert.equal(rangeError("2028-02-29", "2030-02-28"), null);
  assert.ok(rangeError("2028-02-29", "2030-03-01"));
});

function calendarItem(patch = {}) {
  return {
    id: "test:2027:0", is_open_now: false, verified_at: null,
    ...patch,
    programme: {
      slug: "test", name: "Test programme", organiser: "Test organiser", category: "research_internship",
      category_label: "Research", url: "https://example.org/apply", eligibility: null, country: null, geography: null,
      ...patch.programme,
    },
    edition: {
      year: 2027, status: "announced", status_label: "Official", basis: "official",
      opens_at: "2027-01-04T00:00:00+05:30", closes_at: "2027-02-15T23:59:59+05:30",
      opens_precision: "day", closes_precision: "day", opens_until: null, closes_from: null,
      ...patch.edition,
    },
    metadata: {
      deadline_rolling: false, opening_text: null, deadline_text: null, hiring_mode: null,
      ...patch.metadata,
    },
  };
}

test("registration months list opening and closing boundaries in their own months", () => {
  const item = calendarItem();
  const groups = registrationMonths([item], { from: "2027-01-01", to: "2027-03-31" });
  assert.deepEqual(groups.map(({ rows }) => rows.length), [1, 1, 0]);
  assert.equal(groups[0].rows[0].events[0].kind, "opens");
  assert.equal(groups[1].rows[0].events[0].kind, "closes");
  assert.equal(keyDatesText(item, groups[1].rows[0].events), "Registration closes 15 Feb · official");
  assert.equal(registrationMonths([item], { from: "2027-01-10", to: "2027-01-31" })[0].rows.length, 0);
});

test("tentative month precision uses ~Feb, respects month ranges and avoids fabricated days", () => {
  const item = calendarItem({ edition: {
    basis: "tentative", status: "expected", opens_at: "2027-01-01T00:00:00+05:30",
    opens_until: "2027-02-28T23:59:59+05:30", opens_precision: "month",
    closes_at: "2027-03-31T23:59:59+05:30", closes_from: "2027-02-01T00:00:00+05:30", closes_precision: "month",
  } });
  const groups = registrationMonths([item], { from: "2027-01-01", to: "2027-04-30" });
  assert.equal(groups[0].rows[0].events[0].label, "~Jan–Feb");
  assert.equal(groups[1].rows.length, 1);
  assert.equal(groups[1].rows[0].events.length, 2);
  assert.equal(groups[2].rows[0].events[0].label, "~Feb–Mar");
  assert.equal(registrationEvents(calendarItem({ edition: { basis: "tentative", opens_at: "2027-02-01T00:00:00+05:30", opens_precision: "month" } }))[0].label, "~Feb");
  assert.equal(eventsOnDay([item], "2027-02-01").length, 0);
  assert.equal(monthPrecisionItems([item], "2027-02").length, 1);
});

test("12 NITI occurrences collapse to one recurring row and preserve the official rule", () => {
  const items = Array.from({ length: 12 }, (_, month) => {
    const prefix = `2027-${String(month + 1).padStart(2, "0")}`;
    return calendarItem({ id: `niti:2027:${month}`, programme: { slug: "niti", name: "NITI Aayog" },
      edition: { opens_at: `${prefix}-01T00:00:00+05:30`, closes_at: `${prefix}-10T23:59:59+05:30` },
      metadata: { opening_text: "1–10 of EVERY month (official)", deadline_text: "10th of EVERY month (official)" } });
  });
  const result = collapseRecurrences(items, today);
  assert.equal(result.dated.length, 0);
  assert.equal(result.recurring.length, 1);
  assert.equal(result.recurring[0].occurrences.length, 12);
  assert.match(result.recurring[0].rule, /1–10 of EVERY month/);
  assert.equal(collapseRecurrences([items[0]], today).recurring.length, 1);
  const editions = [calendarItem(), calendarItem({ id: "test:2028:0", edition: { year: 2028 } })];
  assert.equal(collapseRecurrences(editions, today).dated.length, 2);
});

test("rolling deadlines have opening text and never become synthetic close events or timeline endpoints", () => {
  const item = calendarItem({ metadata: { deadline_rolling: true }, edition: {
    basis: "tentative", opens_at: "2027-07-01T00:00:00+05:30", opens_precision: "month",
    closes_at: "2027-08-31T23:59:59+05:30", closes_precision: "month",
  } });
  assert.equal(keyDatesText(item), "Opens ~Jul · deadline rolling, apply early");
  assert.equal(registrationEvents(item).length, 1);
  assert.equal(registrationMonths([item], { from: "2027-07-01", to: "2027-10-31" })[1].rows.length, 0);
  assert.deepEqual(timelineWindow(item, ["2027-07", "2027-08", "2027-09", "2027-10"]), { start: 0, end: 3, rolling: true, deadline: null });
  assert.equal(eventsOnDay([item], "2027-08-31").length, 0);
  assert.equal(officialDeadline(item), null);
});

test("period presets cross years, handle leap days and clamp imported ranges to two years", () => {
  assert.deepEqual(periodRange("next12", today), { from: today, to: "2027-11-12" });
  assert.deepEqual(periodRange("next12", "2028-02-29"), { from: "2028-02-29", to: "2029-02-27" });
  assert.deepEqual(periodRange("next30", today), { from: today, to: "2026-12-12" });
  assert.deepEqual(periodRange("next90", today), { from: today, to: "2027-02-10" });
  assert.deepEqual(periodRange("month", today), { from: "2026-11-01", to: "2026-11-30" });
  assert.deepEqual(periodRange("year-2028", today), { from: "2028-01-01", to: "2028-12-31" });
  assert.deepEqual(clampRange("2028-02-29", "2035-01-01"), { from: "2028-02-29", to: "2030-02-28" });
  const long = parseCalendarParams(new URLSearchParams("period=custom&from=2027-01-01&to=2031-01-01"), today);
  assert.equal(long.to, "2029-01-01");
  assert.equal(rangeError(long.from, long.to), null);
  assert.equal(monthsInRange(periodRange("next12", today)).length, 13);
  const next = stepPeriod(parseCalendarParams(new URLSearchParams("period=year-2027"), today), 1);
  assert.equal(next.period, "year-2028");
  assert.equal(next.from, "2028-01-01");
});

test("legacy URLs map their period and presentation and keep deep links and unknown categories", () => {
  const cases = [
    ["view=year&year=2028", "year-2028", "list", "2028-01-01", "2028-12-31"],
    ["view=month&month=2028-02", "month", "grid", "2028-02-01", "2028-02-29"],
    ["view=days&days=90", "next90", "list", today, "2027-02-10"],
    ["view=days&days=7", "custom", "list", today, "2026-11-19"],
    ["view=custom&from=2027-07-01&to=2027-08-31", "custom", "list", "2027-07-01", "2027-08-31"],
  ];
  for (const [url, period, view, from, to] of cases) {
    const query = parseCalendarParams(new URLSearchParams(`${url}&category=government_exam&category=future_category&item=test%3A2027%3A0&q=exam&status=open`), today);
    assert.deepEqual([query.period, query.view, query.from, query.to], [period, view, from, to]);
    assert.equal(query.item, "test:2027:0");
    assert.deepEqual(query.category, ["government_exam", "future_category"]);
    assert.deepEqual(parseCalendarParams(calendarParams(query), today), query);
  }
  for (const view of ["list", "timeline", "grid"]) {
    const query = parseCalendarParams(new URLSearchParams(`period=next12&view=${view}&item=one`), today);
    assert.deepEqual(parseCalendarParams(calendarParams(query), today), query);
  }
  assert.equal(categoryLabel("government_exam"), "Government exams & recruitment");
  assert.equal(categoryLabel("future_category"), "future category");
});

test("closing soon includes today and day 30, excludes day 31 and rolling, and sorts open cards", () => {
  function openIn(days, slug) {
    return calendarItem({ id: slug, programme: { slug }, is_open_now: true,
      edition: { status: "open", closes_at: `${addDays(today, days)}T23:59:59+05:30` } });
  }
  const now = openIn(0, "now");
  const day30 = openIn(30, "day30");
  const day31 = openIn(31, "day31");
  const past = openIn(-1, "past");
  const rolling = { ...openIn(4, "rolling"), metadata: { deadline_rolling: true } };
  assert.equal(daysUntilDeadline(day30, today), 30);
  assert.equal(isClosingSoon(now, today), true);
  assert.equal(isClosingSoon(day30, today), true);
  assert.equal(isClosingSoon(day31, today), false);
  assert.equal(isClosingSoon(past, today), false);
  assert.equal(isClosingSoon(rolling, today), false);
  assert.equal(isClosingSoon(calendarItem(), today), false);
  assert.equal(isClosingSoon(calendarItem({ edition: { closes_at: `${addDays(today, 20)}T23:59:59+05:30` } }), today), true);
  assert.equal(isClosingSoon(calendarItem({ edition: { status: "closed", closes_at: `${addDays(today, 20)}T23:59:59+05:30` } }), today), false);
  assert.deepEqual(selectOpenNow([day31, rolling, day30, past, now, calendarItem()], today).map((item) => item.id), ["now", "day30", "day31", "rolling"]);
  const early = calendarItem({ id: "early", programme: { slug: "early", name: "Z" }, is_open_now: true, edition: { closes_at: `${today}T08:00:00+05:30` } });
  const late = calendarItem({ id: "late", programme: { slug: "late", name: "A" }, is_open_now: true, edition: { closes_at: `${today}T22:00:00+05:30` } });
  assert.deepEqual(selectOpenNow([late, early], today).map((item) => item.id), ["early", "late"]);
});

test("how-to-apply uses supplied bullet steps and derives null-safe official-route guidance", () => {
  assert.deepEqual(howToApply(calendarItem({ metadata: { how_to_apply: "• Register on the portal\n\n2. Submit the form\r\n- Keep the receipt" } })), ["Register on the portal", "Submit the form", "Keep the receipt"]);
  const steps = howToApply(calendarItem({ programme: { eligibility: "Final-year students" }, metadata: { hiring_mode: "Apply through your placement cell" } }));
  assert.match(steps[0], /official site/);
  assert.match(steps[1], /Final-year students/);
  assert.match(steps[2], /placement cell/);
  const absent = howToApply(calendarItem({ programme: { url: "", eligibility: null } }), false);
  assert.equal(absent.length, 3);
  assert.match(absent[0], /organiser’s official website/);
  assert.ok(absent.every((step) => !/null|undefined/.test(step)));
});

test("calendar export is offered only for an official day-precision non-rolling deadline", () => {
  assert.equal(officialDeadline(calendarItem()), "2027-02-15T23:59:59+05:30");
  assert.equal(officialDeadline(calendarItem({ edition: { basis: "tentative" } })), null);
  assert.equal(officialDeadline(calendarItem({ edition: { closes_precision: "month" } })), null);
  assert.equal(officialDeadline(calendarItem({ metadata: { deadline_rolling: true } })), null);
});

test("search and quick filters operate on loaded programme names and organisers", () => {
  const query = parseCalendarParams(new URLSearchParams(), today);
  const item = calendarItem({ programme: { name: "Summer Fellowship", organiser: "CERN", category: "open_source" } });
  assert.equal(filterCalendarItems([item], { ...query, q: "cern" }, today).length, 1);
  assert.equal(filterCalendarItems([item], { ...query, q: "FELLOWSHIP" }, today).length, 1);
  assert.equal(filterCalendarItems([item], { ...query, q: "missing" }, today).length, 0);
  assert.equal(filterCalendarItems([item], { ...query, category: ["open_source"] }, today).length, 1);
  assert.equal(filterCalendarItems([item], { ...query, status: "open" }, today).length, 0);
  assert.equal(filterCalendarItems([calendarItem({ edition: { basis: "tentative" } })], { ...query, officialOnly: true }, today).length, 0);
});

test("period fetching leaves client-side filters out of the unchanged API request", async () => {
  const previous = globalThis.fetch;
  let called;
  globalThis.fetch = async (url) => { called = new URL(url); return { ok: true, json: async () => ({ items: [], rolling: [] }) }; };
  try {
    const query = parseCalendarParams(new URLSearchParams("q=CERN&category=research_internship&status=open&item=one&official=1&closingSoon=1"), today);
    await fetchCalendar(query);
    assert.equal(called.pathname, "/calendar");
    assert.deepEqual([...called.searchParams.keys()].sort(), ["from", "to"]);
    await fetchCalendar({ ...query, from: "2027-01-01", to: "2032-01-01" });
    assert.equal(called.searchParams.get("to"), "2029-01-01");
  } finally { globalThis.fetch = previous; }
});

test("month and day maths handle leap years, year boundaries and DST", () => {
  assert.deepEqual(monthRange("2028-02"), { from: "2028-02-01", to: "2028-02-29" });
  assert.equal(shiftMonth("2027-12", 1), "2028-01");
  assert.equal(shiftMonth("2027-01", -1), "2026-12");
  assert.equal(addDays("2028-02-28", 1), "2028-02-29");
  assert.equal(addDays("2027-12-31", 1), "2028-01-01");
  assert.equal(addDays("2027-03-13", 2), "2027-03-15");
  const cells = calendarDays("2027-02");
  assert.equal(cells.length, 28);
  assert.equal(cells[0], "2027-02-01");
  assert.equal(calendarDays("2028-02").filter(Boolean).length, 29);
  assert.equal(todayIST(new Date("2026-11-13T20:00:00Z")), "2026-11-14");
});

test("day presets include today and have the requested number of days", () => {
  for (const days of [7, 30, 90]) {
    assert.deepEqual(presetRange("days", today, { days }), { from: today, to: addDays(today, days - 1) });
  }
});

test("historical month windows never display a tentative day", () => {
  const item = { edition: {
    opens_at: "2027-01-01T00:00:00+05:30", opens_until: "2027-02-28T23:59:59+05:30",
    closes_at: "2027-03-31T23:59:59+05:30", closes_from: "2027-03-01T00:00:00+05:30",
    opens_precision: "month", closes_precision: "month",
  } };
  assert.equal(windowText(item), "Opens Jan 2027 – Feb 2027 · Deadline Mar 2027");
  item.edition.opens_at = null;
  item.edition.opens_until = null;
  item.edition.closes_at = "2026-12-04T23:59:59+05:30";
  item.edition.closes_precision = "day";
  assert.equal(windowText(item), "Deadline 4 Dec 2026");
});

test("rolling deadlines show the opening window without a synthetic deadline", () => {
  const item = { edition: {
    opens_at: "2027-08-01T00:00:00+05:30", opens_until: "2027-11-30T23:59:59+05:30",
    closes_at: "2027-11-30T23:59:59+05:30", closes_from: null,
    opens_precision: "month", closes_precision: "month",
  }, metadata: { deadline_rolling: true } };
  assert.equal(windowText(item), "Opens Aug 2027 – Nov 2027 · Deadline: rolling — apply early");
  for (const month of ["2027-08", "2027-09", "2027-10", "2027-11"]) {
    assert.equal(openingInMonth(item, month), true);
  }
  assert.equal(openingInMonth(item, "2027-07"), false);
  assert.equal(openingInMonth(item, "2027-12"), false);
  assert.equal(openingInMonth(item, "2028-08"), false);
});
