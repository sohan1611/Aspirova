import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PHASE_PRODUCTION_BUILD } from "next/constants.js";
import { testModuleLoader } from "../scripts/test-module.mjs";

const offline = async () => { throw new Error("API unavailable"); };
const count = data => data.items.length;

for (const vercel of [undefined, "0"]) {
  test("CI/local build returns failed/null outside Vercel=" + vercel, async () => {
    const load = testModuleLoader({}, { process: { env: { NEXT_PHASE: PHASE_PRODUCTION_BUILD, VERCEL: vercel } } });
    const state = await load("lib/buildFallback.ts").withBuildFallback(offline, count);
    assert.equal(state.status, "failed");
    assert.equal(state.data, null);
    assert.equal(state.loadedAt, null);
    assert.equal(Object.hasOwn(state, "total"), false);
  });
}

for (const env of [
  { NEXT_PHASE: PHASE_PRODUCTION_BUILD, VERCEL: "1" },
  { NEXT_PHASE: "phase-production-server", VERCEL: "1" },
  { NEXT_PHASE: "phase-production-server" },
  {},
]) {
  test("Vercel builds and runtime rethrow " + JSON.stringify(env), async () => {
    const load = testModuleLoader({}, { process: { env } });
    await assert.rejects(load("lib/buildFallback.ts").withBuildFallback(offline, count), /API unavailable/);
  });
}

test("successful true zero remains empty even in an offline-capable build", async () => {
  const load = testModuleLoader({}, { process: { env: { NEXT_PHASE: PHASE_PRODUCTION_BUILD } } });
  const data = { items: [], total: 0 };
  const state = await load("lib/buildFallback.ts").withBuildFallback(async () => data, count);
  assert.equal(state.status, "empty");
  assert.equal(state.data, data);
});

test("a null default prerender automatically loads the client store on mount", async () => {
  let calls = 0;
  const load = testModuleLoader({ react: {
    useCallback: fn => fn,
    useEffect: effect => effect(),
    useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot(),
  } });
  const listing = load("lib/listingResults.ts");
  const fetch = async () => { calls++; return { items: [{ slug: "healed" }], total: 1 }; };
  const view = () => listing.useListingResults("/", "", false, fetch, null);
  assert.equal(view().settled, null);
  await new Promise(setImmediate);
  assert.equal(view().settled.status, "results");
  assert.equal(view().settled.data.items[0].slug, "healed");
  assert.equal(calls, 1);
});

test("an existing successful default prerender makes no mount-time request", async () => {
  let calls = 0;
  const load = testModuleLoader({ react: {
    useCallback: fn => fn,
    useEffect: effect => effect(),
    useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot(),
  } });
  load("lib/listingResults.ts").useListingResults("/", "", false, async () => { calls++; }, { items: [], total: 0 });
  await new Promise(setImmediate);
  assert.equal(calls, 0);
});

const component = fn => ({ __esModule: true, default: fn });
const hidden = component(() => null);

for (const kind of ["programme", "companies", "company"]) {
  test("offline " + kind + " shell fetches on mount and heals without Retry", async () => {
    const slots = []; let index = 0; const effects = []; let calls = 0;
    const request = async () => {
      calls++;
      if (kind === "companies") return [{ slug: "acme", name: "Acme", active_count: 1 }];
      if (kind === "company") return { company: { name: "Acme", slug: "acme" }, items: [{ slug: "engineer" }], total: 1 };
      return { items: [{ slug: "summer", name: "Summer programme" }], total: 1 };
    };
    const load = testModuleLoader({
      react: {
        useCallback: fn => fn,
        useState(initial) {
          const slot = index++;
          if (!(slot in slots)) slots[slot] = typeof initial === "function" ? initial() : initial;
          return [slots[slot], value => { slots[slot] = typeof value === "function" ? value(slots[slot]) : value; }];
        },
        useEffect: effect => effects.push(effect),
      },
      "next/link": component(({ children }) => React.createElement("a", null, children)),
      "@/lib/api": { getProgrammes: request, getCompanies: request, getCompanyPage: request },
      "@/components/CompanyFavicon": hidden,
      "@/components/CompanyOpportunities": component(({ data }) => React.createElement("p", null, data.company.name)),
      "@/components/ProgrammeCard": component(({ programme }) => React.createElement("p", null, programme.name)),
      "@/components/ProgrammeAlmanac": hidden,
      "@/components/ListingFeedback": {
        ListingFailure: () => React.createElement("p", null, "Couldn't load results. Retry"),
        ListingEmpty: () => React.createElement("p", null, "True zero"),
      },
    });
    const exports = load("components/BuildListingRecovery.tsx");
    const render = () => {
      index = 0;
      return kind === "programme" ? exports.ProgrammeBuildRecovery({ params: { category: ["fellowship"] } })
        : kind === "companies" ? exports.CompaniesBuildRecovery() : exports.CompanyBuildRecovery({ slug: "acme", page: 1, limit: 20 });
    };
    assert.match(renderToStaticMarkup(render()), /Couldn&#x27;t load results/);
    effects.splice(0).forEach(effect => effect());
    await new Promise(setImmediate);
    const html = renderToStaticMarkup(render());
    assert.match(html, kind === "programme" ? /Summer programme/ : /Acme/);
    assert.doesNotMatch(html, /True zero|Couldn&#x27;t load results/);
    assert.equal(calls, 1);
  });
}
