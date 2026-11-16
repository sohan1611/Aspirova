// Run with node --test lib/programmeWatches.test.mjs (Node 23.6+).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addProgrammeWatch, getProgrammeWatches, removeProgrammeWatch, WATCH_LIMIT_COPY,
} from "./programmeWatches.ts";
import { programmeEligibility, UNCONFIRMED_ELIGIBILITY } from "./programmeEligibility.ts";
import { isNotificationEnabled, isNotificationLocked } from "./notificationPrefs.ts";

test("missing and whitespace-only eligibility stay explicitly unconfirmed", () => {
  for (const value of [null, undefined, "", "   ", "\n\t"]) {
    assert.equal(programmeEligibility(value), "Eligibility not confirmed — check the official page");
  }
  assert.equal(programmeEligibility("  Final-year students  "), "Final-year students");
  assert.equal(programmeEligibility(null), UNCONFIRMED_ELIGIBILITY);
});

test("watch email preferences are available on every plan and honour explicit opt-out", () => {
  const account = { plan: { features: { daily_digest: false } }, notification_prefs: {} };
  assert.equal(isNotificationLocked("daily_digest", account), false);
  assert.equal(isNotificationEnabled("daily_digest", account), true);
  account.notification_prefs.daily_digest = false;
  assert.equal(isNotificationEnabled("daily_digest", account), false);
});

test("watch reads are authenticated and never cached", async (context) => {
  const items = [{ id: 1, programme_slug: "test", programme_name: "Test programme" }];
  const fetchMock = context.mock.method(globalThis, "fetch", async (url, options) => {
    assert.match(url, /\/calendar\/watches$/);
    assert.equal(options.method, "GET");
    assert.equal(options.headers.Authorization, "Bearer test-session");
    assert.equal(options.cache, "no-store");
    return Response.json(items);
  });
  assert.deepEqual(await getProgrammeWatches("test-session"), items);
  assert.equal(fetchMock.mock.calls.length, 1);
});

test("watch actions encode the programme slug and accept empty delete responses", async (context) => {
  const item = { id: 1, programme_slug: "test / window" };
  const requests = [];
  context.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push([url, options.method]);
    return options.method === "DELETE" ? new Response(null, { status: 204 }) : Response.json(item);
  });
  assert.deepEqual(await addProgrammeWatch("test / window", "test-session"), item);
  await removeProgrammeWatch("test / window", "test-session");
  assert.equal(requests.length, 2);
  assert.deepEqual(requests.map((entry) => entry[1]), ["PUT", "DELETE"]);
  for (const [url] of requests) assert.match(url, /\/calendar\/test%20%2F%20window\/watch$/);
});

test("watch limit, expired auth and missing programmes give actionable errors", async (context) => {
  let status = 409;
  context.mock.method(globalThis, "fetch", async () => new Response(null, { status }));
  await assert.rejects(addProgrammeWatch("test", "test-session"), { message: WATCH_LIMIT_COPY });
  for (status of [401, 403]) await assert.rejects(getProgrammeWatches("test-session"), /session has expired/);
  status = 404;
  await assert.rejects(addProgrammeWatch("test", "test-session"), /no longer available/);
  status = 500;
  await assert.rejects(removeProgrammeWatch("test", "test-session"), /Please try again/);
});

test("watch loading supports cancellation", async (context) => {
  const controller = new AbortController();
  context.mock.method(globalThis, "fetch", async (_url, options) => {
    assert.equal(options.signal, controller.signal);
    throw new DOMException("Aborted", "AbortError");
  });
  controller.abort();
  await assert.rejects(getProgrammeWatches("test-session", controller.signal), { name: "AbortError" });
});
