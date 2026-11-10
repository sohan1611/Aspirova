// Run with node --test lib/jobPostingJsonLd.test.mjs (Node 23.6+).
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import ts from "typescript";
import * as descriptionBlocks from "./descriptionBlocks.ts";
import { isListingClosed } from "./deadline.ts";

// Resolve the builder's extensionless TS import using the actual shared helper.
const source = ts.transpileModule(
  fs.readFileSync(new URL("./jobPostingJsonLd.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } },
).outputText;
const loaded = { exports: {} };
vm.runInNewContext(source, {
  module: loaded,
  exports: loaded.exports,
  require: (name) => {
    assert.equal(name, "./descriptionBlocks");
    return descriptionBlocks;
  },
});
const { buildJobPostingJsonLd } = loaded.exports;

const canonicalUrl = "https://www.aspirova.org/opportunity/engineer";
const opportunity = {
  title: "Software Engineer",
  category: "job",
  company: {
    name: "Example Company",
    domain: "example.com",
    logo_url: "https://example.com/logo.png",
  },
  posted_at: "2026-11-01T10:00:00Z",
  first_seen_at: "2026-11-05T12:00:00Z",
  country: "IN",
  location: "Bengaluru",
  is_remote: false,
  is_stale: false,
  is_hidden: false,
  closed_at: null,
  deadline: null,
  deadline_confidence: "unknown",
  description_raw: "Build APIs & ship features.",
};

function build(overrides = {}) {
  const row = { ...opportunity, ...overrides };
  return buildJobPostingJsonLd(
    row,
    canonicalUrl,
    isListingClosed(row.closed_at, row.deadline, row.category),
    descriptionBlocks.parseDescriptionBlocks(row.description_raw),
  );
}

test("sourced posting date and existing JobPosting fields are preserved", () => {
  const result = build();
  assert.equal(result.datePosted, opportunity.posted_at);
  assert.equal(result["@context"], "https://schema.org");
  assert.equal(result["@type"], "JobPosting");
  assert.equal(result.title, opportunity.title);
  assert.equal(result.description, "<p>Build APIs &amp; ship features.</p>");
  assert.equal(result.url, canonicalUrl);
  assert.equal(result.directApply, false);
  assert.equal(result.hiringOrganization["@type"], "Organization");
  assert.equal(result.hiringOrganization.name, opportunity.company.name);
  assert.equal(result.hiringOrganization.sameAs, "https://example.com");
  assert.equal(result.hiringOrganization.logo, opportunity.company.logo_url);
  assert.equal(result.jobLocation.address.addressCountry, "IN");
  assert.equal(result.jobLocation.address.addressLocality, "Bengaluru");
});

test("missing or blank posting dates omit markup despite a first-seen date", () => {
  for (const posted_at of [null, undefined, "", "   "]) {
    assert.equal(build({ posted_at }), null);
  }
});

for (const category of ["competition", "hackathon", "scholarship", null]) {
  test(`${category} category omits JobPosting`, () => {
    assert.equal(build({ category }), null);
  });
}

test("closed, expired, stale, hidden and unknown-remote listings omit markup", () => {
  for (const overrides of [
    { closed_at: "2020-01-01T00:00:00Z" },
    { deadline: "2020-01-01T00:00:00Z" },
    { is_stale: true },
    { is_hidden: true },
    { is_remote: null },
  ]) {
    assert.equal(build(overrides), null);
  }
});

test("all existing required fields remain mandatory", () => {
  for (const overrides of [
    { title: "  " },
    { description_raw: "  " },
    { company: null },
    { company: { name: "  " } },
    { country: "  " },
  ]) {
    assert.equal(build(overrides), null);
  }
});

test("validThrough requires an explicit deadline", () => {
  const deadline = "2099-12-31T23:59:59Z";
  assert.equal(build({ deadline, deadline_confidence: "explicit" }).validThrough, deadline);
  for (const deadline_confidence of ["inferred", "unknown"]) {
    assert.equal(Object.hasOwn(build({ deadline, deadline_confidence }), "validThrough"), false);
  }
  assert.equal(Object.hasOwn(build({ deadline_confidence: "explicit" }), "validThrough"), false);
});

test("remote internships retain employment type and applicant country", () => {
  const result = build({ category: "internship", is_remote: true });
  assert.equal(result.employmentType, "INTERN");
  assert.equal(result.jobLocationType, "TELECOMMUTE");
  assert.equal(result.applicantLocationRequirements["@type"], "Country");
  assert.equal(result.applicantLocationRequirements.name, "IN");
  assert.equal(Object.hasOwn(result, "jobLocation"), false);
});

test("salary metadata never emits baseSalary", () => {
  for (const category of ["job", "internship"]) {
    for (const is_remote of [true, false]) {
      const result = build({
        category,
        is_remote,
        meta: { compensation: { min: 50000, max: 100000, currency: "INR" } },
      });
      assert.equal(Object.hasOwn(result, "baseSalary"), false);
    }
  }
});
