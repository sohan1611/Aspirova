import assert from "node:assert/strict";
import { test } from "node:test";
import { testModuleLoader } from "../scripts/test-module.mjs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const load = testModuleLoader({}, { URL });
const { destinationFacts, destinationLines, describeApply } = load("lib/applyDestination.ts");
const { safeExternalUrl } = load("lib/safeUrl.ts");
const facts = overrides => ({ v: 1, valid: true, host: "jobs.lever.co", domain: "lever.co",
  type: "employer_ats", employer_verified: false, aggregator_warning: false,
  via: null, status: "unchecked", warnings: [], ...overrides });

test("missing facts and all positive integer versions are tolerated", () => {
  assert.equal(destinationFacts(null), null);
  assert.equal(destinationFacts({}), null);
  for (const v of [1, 2, 99]) assert.equal(destinationFacts(facts({ v })).v, v);
  for (const v of [0, -1, 1.5, "1"]) assert.equal(destinationFacts(facts({ v })), null);
});

test("employer ownership requires stored verification, including old ATS copy", () => {
  const legacy = { kind: "ats", host: "jobs.lever.co", label: "Lever" };
  assert.doesNotMatch(describeApply(legacy, "Acme").caption, /Acme's careers|Acme's own/);
  assert.match(describeApply(legacy, "Acme", facts({})).caption, /not been verified/);
  assert.match(describeApply(legacy, "Acme", facts({ employer_verified: true })).caption, /Acme's verified/);
});

test("aggregator, auth and redirect warnings name only the observed hosts", () => {
  const lines = destinationLines(facts({ type: "aggregator", host: "himalayas.app",
    aggregator_warning: true, via: "Himalayas", status: "sign_in_required",
    terminal_host: "accounts.example.com", warnings: ["redirect_unrelated"] }));
  const text = lines.join(". ");
  assert.match(text, /Applies on himalayas.app/);
  assert.match(text, /Listed via Himalayas — not the employer's own page/);
  assert.match(text, /Sign-in required/);
  assert.match(text, /Redirect target: accounts.example.com/);
  assert.match(text, /Redirect could not be verified/);
  assert.deepEqual(Array.from(destinationLines(null)), []);
  const direct = destinationLines(facts({ type: "employer_site", employer_verified: true,
    aggregator_warning: true, via: "GitHub lists", host: "careers.example.com" })).join(". ");
  assert.match(direct, /Listed via GitHub lists/);
  assert.doesNotMatch(direct, /not the employer's own page/);
});

test("private, credential and malformed Apply links are blocked after browser normalization", () => {
  for (const value of ["http://127.1", "http://2130706433", "http://0x7f000001", "http://10.0.0.1",
    "https://user:pass@example.com", "https://localhost", "https://x.localhost", "https://bad_host.com",
    "http://[::ffff:127.0.0.1]", "http://[fe80::1]", "http://169.254.169.254", "mailto:a@example.com",
    "https://example.com\\@evil.com", "https://example.com/\npath"]) assert.equal(safeExternalUrl(value), null);
  assert.equal(safeExternalUrl("https://careers.example.com/job?utm_source=x"), "https://careers.example.com/job?utm_source=x");
  assert.equal(safeExternalUrl("https://example.com?email=applicant@example.org"), "https://example.com?email=applicant@example.org");
  assert.equal(safeExternalUrl("https://@example.com"), null);
});

test("real notice DOM wraps long hosts and renders external auth evidence", () => {
  const Label = load("components/DestinationLabel.tsx").default;
  const html = renderToStaticMarkup(React.createElement(Label, { facts:
    facts({ host: `careers.${"a".repeat(63)}.example.com`, status: "sign_in_required" }) }));
  assert.match(html, /Applies on careers/);
  assert.match(html, /Sign-in required at the destination/);
  assert.match(html, /overflow-wrap:anywhere/);
  assert.match(html, /min-w-0 max-w-full/);
});

test("blocked 403 and 429 do not add a sign-in label or an unknown notice", () => {
  const Label = load("components/DestinationLabel.tsx").default;
  for (const code of [403, 429]) {
    const unknown = facts({ status: "unknown", warnings: [`blocked_${code}`] });
    assert.deepEqual(Array.from(destinationLines(unknown)), Array.from(destinationLines(facts({}))));
    const html = renderToStaticMarkup(React.createElement(Label, { facts: unknown }));
    assert.doesNotMatch(html, /Sign-in required|blocked_|unknown/i);
  }
});

test("Unstop event copy names the platform without an employer-origin claim", () => {
  const event = facts({ v: 2, host: "unstop.com", domain: "unstop.com", type: "competition_platform",
    platform: "Unstop", employer_verified: false, via: null, aggregator_warning: false });
  const lines = destinationLines(event).join(". ");
  assert.match(lines, /Hosted on Unstop \(unstop.com\)/);
  assert.doesNotMatch(lines, /employer|own page|aggregator/i);
  const copy = describeApply({ kind: "event_platform", host: "unstop.com", label: "Unstop" }, "Unstop", event);
  assert.match(copy.caption, /hosted on Unstop/);
  assert.doesNotMatch(copy.caption, /own|verified careers|employer/i);
  const Label = load("components/DestinationLabel.tsx").default;
  const fallback = renderToStaticMarkup(React.createElement(Label, {
    destination: { kind: "event_platform", host: "unstop.com", label: "Unstop" },
  }));
  assert.match(fallback, /Hosted on Unstop/);
  assert.doesNotMatch(fallback, /employer|own page/i);
});

test("Unstop jobs keep aggregator disclosure", () => {
  const job = facts({ v: 2, host: "unstop.com", type: "aggregator", via: "Unstop", aggregator_warning: true });
  assert.match(destinationLines(job).join(". "), /Listed via Unstop — not the employer's own page/);
});
