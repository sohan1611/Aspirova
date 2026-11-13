// Run with node --test lib/hiringCalendar.test.mjs (Node 23.6+).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addDays, calendarDays, calendarParams, currentCycleYear, monthRange,
  openingInMonth, parseCalendarParams, presetRange, programmeSummaryName, rangeError, shiftMonth, todayIST, validDay, windowText,
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

test("default range uses the current programme cycle", () => {
  const query = parseCalendarParams(new URLSearchParams(), today);
  assert.equal(currentCycleYear(today), 2027);
  assert.equal(currentCycleYear("2029-01-01"), 2029);
  assert.equal(query.view, "year");
  assert.equal(query.from, "2027-01-01");
  assert.equal(query.to, "2027-12-31");
});

test("URL round trip preserves range, categories, status and query", () => {
  for (const view of ["year", "month", "days", "custom"]) {
    const query = parseCalendarParams(new URLSearchParams({ view, year: "2028", month: "2028-02", days: "90" }), today);
    query.category = ["early_career", "government_internship"];
    query.status = "expected";
    query.q = "IIT & research";
    assert.deepEqual(parseCalendarParams(calendarParams(query), today), query);
    const api = calendarParams(query, true);
    assert.equal(api.has("view"), false);
    assert.deepEqual(api.getAll("category"), query.category);
  }
});

test("invalid params safely return canonical ranges", () => {
  const query = parseCalendarParams(new URLSearchParams("view=custom&from=2027-02-30&to=2030-02-01&category=junk&status=junk"), today);
  assert.equal(query.from, today);
  assert.deepEqual(query.category, []);
  assert.equal(query.status, "");
  assert.equal(validDay("2027-02-29"), false);
  assert.equal(validDay("2028-02-29"), true);
  assert.ok(rangeError("2027-03-01", "2027-02-01"));
  assert.ok(rangeError("2027-01-01", "2029-01-02"));
  assert.equal(rangeError("2028-02-29", "2030-02-28"), null);
  assert.ok(rangeError("2028-02-29", "2030-03-01"));
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
