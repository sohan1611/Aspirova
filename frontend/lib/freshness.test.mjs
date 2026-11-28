import assert from "node:assert/strict";
import { test } from "node:test";
import { testModuleLoader } from "../scripts/test-module.mjs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const { freshnessText } = testModuleLoader({})("lib/freshness.ts");
const now = Date.parse("2026-11-26T12:00:00Z");
test("freshness tolerates missing and invalid data without inventing verification", () => {
  assert.equal(freshnessText({}, now), null);
  assert.equal(freshnessText({ last_verified_at: "bad" }, now), null);
  assert.equal(freshnessText({ freshness: "stale" }, now), "Not verified recently");
});
test("relative verification and stale age use successful evidence, including old ISR data", () => {
  const item = { last_verified_at: "2026-11-24T12:00:00Z", stale_after_hours: 168 };
  assert.equal(freshnessText(item, now), "Verified 2 days ago");
  assert.equal(freshnessText(item, now + 8 * 86_400_000), "Not verified recently");
  assert.equal(freshnessText(item), "Verified 24 Nov 2026");
});
test("old evergreen postings remain stale without inventing an old verification date", () => {
  assert.equal(freshnessText({ freshness: "stale", freshness_reason: "age",
    last_verified_at: "2026-11-26T12:00:00Z" }, now), "Old posting — check source");
});
test("freshness DOM wraps within narrow cards and detail columns", () => {
  const load = testModuleLoader({ "@/lib/useHydrated": { useHydrated: () => false } });
  const Label = load("components/FreshnessLabel.tsx").default;
  const markup = renderToStaticMarkup(React.createElement(Label, { item: { freshness: "stale" } }));
  assert.match(markup, /Not verified recently/);
  assert.match(markup, /min-w-0 max-w-full/);
  assert.match(markup, /overflow-wrap:anywhere/);
});
