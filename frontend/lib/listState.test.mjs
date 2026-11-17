import assert from "node:assert/strict";
import { test } from "node:test";
import { testModuleLoader } from "../scripts/test-module.mjs";

const load = testModuleLoader();
const { loadedList, failedList, listJson, requestSequence, emptyFilterLinks, relativeResultTime } = load("lib/listState.ts");

for (const [items, expected] of [[[1], "results"], [[], "empty"]]) {
  test(`2xx ${expected} is an explicit successful state`, async () => {
    const data = await listJson(Response.json({ items }));
    assert.equal(loadedList(data, data.items.length, 123).status, expected);
  });
}

for (const status of [429, 500, 502, 503, 504]) {
  test(`${status} is failed, never empty, and retains its snapshot time`, async () => {
    const previous = loadedList({ items: [1] }, 1, 123);
    await assert.rejects(listJson(new Response("unavailable", { status })), new RegExp(String(status)));
    const failed = failedList(previous);
    assert.equal(failed.status, "failed");
    assert.equal(failed.data, previous.data);
    assert.equal(failed.loadedAt, 123);
  });
}

test("network and invalid JSON failures cannot become a successful zero", async () => {
  for (const request of [() => Promise.reject(new Error("offline")), () => listJson(new Response("not JSON", { status: 200 }))]) {
    let state;
    try { const data = await request(); state = loadedList(data, 0); } catch { state = failedList(null); }
    assert.equal(state.status, "failed");
    assert.equal(state.data, null);
  }
});

test("a superseded request cannot publish, including after cleanup", () => {
  const sequence = requestSequence();
  const first = sequence.start();
  const next = sequence.start();
  assert.equal(sequence.isCurrent(first), false);
  assert.equal(sequence.isCurrent(next), true);
  sequence.cancel();
  assert.equal(sequence.isCurrent(next), false);
});

test("removing one repeated filter preserves every other URL value and resets pagination", () => {
  const links = emptyFilterLinks("/jobs", new URLSearchParams("q=data&company=A&company=B&location=Delhi&page=4&sort=pay"));
  const link = links.find(link => link.label === "Company: A");
  const query = new URL(link.href, "https://example.org").searchParams;
  assert.deepEqual(query.getAll("company"), ["B"]);
  assert.equal(query.get("q"), "data");
  assert.equal(query.get("location"), "Delhi");
  assert.equal(query.get("sort"), "pay");
  assert.equal(query.has("page"), false);
  assert.equal(links.length, 4);
  assert.equal(relativeResultTime(0, 120_000), "2 minutes ago");
});

test("chip labels reuse human country, role, category and role-signal labels", () => {
  const links = emptyFilterLinks("/jobs", new URLSearchParams("q=data&country=IN&role=software&category=job&experience=new_grad&paid=true&posted_within=7"));
  assert.deepEqual(links.map(link => link.label), [
    "Search: data", "Country: India", "Role: Software", "Category: Jobs",
    "Experience: New grad roles", "Paid only", "Past 7 days",
  ]);
});

test("programme and competition chips use facet labels and category configuration", () => {
  const facets = {
    companies: [], locations: [],
    programme_fields: [{ value: "cs", label: "Computer Science", count: 2 }],
    programme_institution_types: [{ value: "national", label: "Institute of National Importance", count: 1 }],
    modes: [{ value: "offline", label: "In person", count: 3 }],
  };
  const links = emptyFilterLinks("/programmes", new URLSearchParams("category=research_internship&field=cs&institution_type=national&mode=offline"), facets);
  assert.deepEqual(links.map(link => link.label), [
    "Category: Research internship", "Field: Computer Science",
    "Institution type: Institute of National Importance", "Mode: In person",
  ]);
});

test("unknown parameters get a tidied key while preserving their original value and URL", () => {
  const [chip] = emptyFilterLinks("/jobs", new URLSearchParams("future_filter=exact-value&company=ACME"));
  assert.equal(chip.label, "Future Filter: exact-value");
  assert.equal(chip.href, "/jobs?company=ACME");
});
