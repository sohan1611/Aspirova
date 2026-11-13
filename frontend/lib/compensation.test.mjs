// Run with node --test lib/compensation.test.mjs (Node 23.6+).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { formatCompensation } from "./compensation.ts";

const fixtures = new URL("../../backend/tests/fixtures/pay/", import.meta.url);
const displayCases = JSON.parse(fs.readFileSync(new URL("display_cases.json", fixtures), "utf8"));

for (const { name, pay, display } of displayCases) {
  test(name, () => {
    assert.equal(formatCompensation({ compensation: pay }), display);
  });
}

for (const file of fs.readdirSync(fixtures).filter((file) => file.includes("-"))) {
  const fixture = JSON.parse(fs.readFileSync(new URL(file, fixtures), "utf8"));
  test(`${fixture.slug} hides stored bad pay before backfill`, () => {
    assert.equal(formatCompensation({ compensation: fixture.previous_compensation }), null);
    assert.equal(formatCompensation({
      compensation: { ...fixture.previous_compensation, paid: true },
    }), "Paid");
    assert.equal(formatCompensation({ compensation: fixture.expected_compensation }),
      fixture.expected_compensation ? "$250/week" : null);
  });
}

test("malformed and nonfinite values never display amounts", () => {
  for (const amount of [Infinity, -Infinity, NaN, true, [], {}, "800"]) {
    assert.equal(formatCompensation({ compensation: {
      min: amount, max: amount, currency: "USD", period: "hour", paid: true,
    } }), "Paid");
  }
  for (const compensation of [undefined, null, [], "Paid", true]) {
    assert.equal(formatCompensation({ compensation }), null);
  }
  for (const currency of ["constructor", "toString", "__proto__"]) {
    assert.equal(formatCompensation({ compensation: {
      min: 25, max: 25, currency, period: "hour",
    } }), null);
  }
});
