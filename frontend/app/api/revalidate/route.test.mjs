import assert from "node:assert/strict";
import { test } from "node:test";
import { testModuleLoader } from "../../../scripts/test-module.mjs";

const secret = "test-revalidation-secret";

function harness({ purgeError, configured = true } = {}) {
  const paths = [];
  const purges = [];
  const errors = [];
  const events = [];
  const load = testModuleLoader({
    "next/cache": { revalidatePath: (...args) => { paths.push(args); events.push("path"); } },
    "@vercel/functions": { dangerouslyDeleteByTag: async tags => {
      purges.push([...tags]);
      events.push("purge");
      if (purgeError) throw purgeError;
    } },
    "@/lib/landing": {
      REVALIDATABLE_LIST_PATHS: ["/", "/jobs", "/internships", "/remote", "/scholarships", "/competitions"],
      PAGINATED_LANDING_PATHS: ["/jobs", "/internships", "/remote", "/scholarships"],
    },
  }, {
    Buffer,
    process: { env: { REVALIDATE_SECRET: configured ? secret : undefined } },
    console: { error: (...args) => errors.push(args) },
  });
  const { POST } = load("app/api/revalidate/route.ts");
  const request = (body, authorization = `Bearer ${secret}`) => POST(new Request("http://example.test/api/revalidate", {
    method: "POST",
    headers: { authorization, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
  return { request, POST, paths, purges, errors, events };
}

test("purges unique valid opportunity tags after path revalidation", async () => {
  const { request, paths, purges, events } = harness();
  const response = await request({
    slugs: ["first-role", "first-role", "second-role", "bad,slug", "Uppercase", "a".repeat(121), "", null],
    paths: ["/jobs", "/jobs", "/competitions", "/not-allowed"],
  });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { revalidated: 2, paths: 2, purged: 2 });
  assert.deepEqual(purges, [["opportunity-first-role", "opportunity-second-role"]]);
  assert.deepEqual(paths, [["/opportunity/first-role"], ["/opportunity/second-role"], ["/jobs"], ["/jobs/page/[n]", "page"], ["/competitions"]]);
  assert.deepEqual(events, ["path", "path", "purge", "path", "path", "path"]);
});

test("purge failure logs and still revalidates list paths with a 200", async () => {
  const failure = new Error("CDN unavailable");
  const { request, paths, purges, errors } = harness({ purgeError: failure });
  const response = await request({ slugs: ["closed-role"], paths: ["/", "/jobs"] });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { revalidated: 1, paths: 2, purged: 0 });
  assert.deepEqual(purges, [["opportunity-closed-role"]]);
  assert.deepEqual(paths, [["/opportunity/closed-role"], ["/"], ["/jobs"], ["/jobs/page/[n]", "page"]]);
  assert.equal(errors.length, 1);
  assert.match(errors[0][0], /purge.*CDN cache/);
  assert.equal(errors[0][1], failure);
});

for (const body of [{ paths: ["/jobs"] }, { slugs: [] }, { slugs: ["bad,slug", "UPPER"] }]) {
  test("skips CDN purge when no valid slugs remain: " + JSON.stringify(body), async () => {
    const { request, purges } = harness();
    const response = await request(body);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).purged, 0);
    assert.deepEqual(purges, []);
  });
}

test("retains the 500-entry batch limit before slug deduplication", async () => {
  const { request, purges } = harness();
  const response = await request({ slugs: [...Array(500).fill("first-role"), "outside-batch"] });
  assert.deepEqual(await response.json(), { revalidated: 1, paths: 0, purged: 1 });
  assert.deepEqual(purges, [["opportunity-first-role"]]);
});

test("keeps authentication, configuration and body checks ahead of cache changes", async () => {
  const { request, POST, paths, purges } = harness();
  assert.equal((await request({ slugs: ["role"] }, "Bearer wrong")).status, 401);
  assert.equal((await request({ slugs: ["role"] }, "")).status, 401);
  assert.equal((await request({})).status, 400);
  assert.equal((await request(null)).status, 400);
  assert.equal((await request({ slugs: "role" })).status, 400);
  assert.equal((await POST(new Request("http://example.test/api/revalidate", {
    method: "POST", headers: { authorization: `Bearer ${secret}` }, body: "invalid JSON",
  }))).status, 400);
  assert.equal((await harness({ configured: false }).request({ slugs: ["role"] })).status, 503);
  assert.deepEqual(paths, []);
  assert.deepEqual(purges, []);
});
