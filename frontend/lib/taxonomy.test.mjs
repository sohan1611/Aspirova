import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { testModuleLoader } from "../scripts/test-module.mjs";

const taxonomy = JSON.parse(fs.readFileSync(new URL("./taxonomy.json", import.meta.url), "utf8"));
const { expandToSearchTerms, buildFeedTerms } = testModuleLoader({
  "@/lib/taxonomy.json": taxonomy,
})("lib/taxonomy.ts");

test("every taxonomy key expands through its selected division in stable order", () => {
  for (const stream of taxonomy.streams) {
    for (const division of stream.divisions) {
      for (const interest of division.interests) {
        const profile = { stream: stream.key, divisions: [division.key], interests: [interest.key], country: null };
        const expected = [...new Set((interest.keywords ?? [interest.label]).map(term => term.trim().toLowerCase()).filter(Boolean))];
        assert.deepEqual(Array.from(expandToSearchTerms(profile)), expected);
        assert.deepEqual(Array.from(expandToSearchTerms({ ...profile, divisions: [] })), []);
      }
    }
  }
});

test("feed terms preserve interest priority, deduplication and stop-on-overflow", () => {
  const profile = { stream: "engineering", divisions: ["cse"], interests: ["data_science"], country: "IN" };
  assert.deepEqual(Array.from(buildFeedTerms(profile, [" Python ", "PYTHON", "SQL"])), ["data science", "python", "sql"]);
  assert.deepEqual(Array.from(buildFeedTerms(profile, ["Python", "SQL"], 16)), ["data science"]);
  assert.deepEqual(Array.from(expandToSearchTerms({ ...profile, stream: "missing" })), []);
});
