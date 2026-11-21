import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import vm from "node:vm";
import { testModuleLoader } from "../scripts/test-module.mjs";

const require = createRequire(import.meta.url);
const week = 604800;
const company = { company: { slug: "example", name: "Example" }, items: [], total: 60, limit: 20 };
const companyRoutes = ["app/companies/[slug]/page.tsx", "app/companies/[slug]/page/[n]/page.tsx"];
const component = () => null;

function harness(response = () => Response.json(company), globals = {}) {
  const reads = [];
  const tags = [];
  const cached = [];
  const events = [];
  const load = testModuleLoader({
    react: { cache: fn => {
      const values = new Map();
      return (...args) => {
        const key = JSON.stringify(args);
        if (!values.has(key)) values.set(key, fn(...args));
        return values.get(key);
      };
    } },
    "@vercel/functions": { addCacheTag: async tag => { tags.push(tag); events.push("tag"); } },
    "next/cache": { unstable_cache: (fn, _key, options) => { cached.push(options); return fn; } },
    "next/navigation": {
      notFound() { throw new Error("not found"); },
      redirect(path) { throw new Error("redirect: " + path); },
    },
    "@/components/BuildListingRecovery": { CompanyBuildRecovery: component },
    "@/components/CompanyOpportunities": { __esModule: true, default: component },
    "@/components/SourceCompanyDetail": { __esModule: true, default: component },
  }, {
    fetch: async (...args) => { reads.push(args); events.push("fetch"); return response(...args); },
    ...globals,
  });
  return { load, reads, tags, cached, events };
}

for (const route of companyRoutes) {
  test(route + " shares one uncached API read between metadata and page", async () => {
    const { load, reads, tags, cached, events } = harness();
    const page = load(route);
    assert.equal(page.dynamic, "force-dynamic");
    assert.equal(Object.hasOwn(page, "revalidate"), false);
    assert.equal(Object.hasOwn(page, "generateStaticParams"), false);
    const props = { params: Promise.resolve({ slug: "example", n: "2" }) };
    const rendered = await page.default(props);
    const metadata = await page.generateMetadata(props);
    assert.equal(metadata.title, "Example opportunities");
    assert.equal(reads.length, 1);
    assert.equal(reads[0][1].cache, "no-store");
    assert.equal(rendered.props.data.expiresAt - rendered.props.data.loadedAt, week * 1000);
    assert.deepEqual(tags, ["company-example"]);
    assert.deepEqual(cached, []);
    assert.deepEqual(events, ["tag", "fetch"]);
    const pageNumber = route === companyRoutes[0] ? 1 : 2;
    assert.equal(new URL(reads[0][0]).searchParams.get("page"), String(pageNumber));
    assert.equal(metadata.alternates.canonical, pageNumber === 1 ? "/companies/example" : "/companies/example/page/2");
  });

  test(route + " validates CDN tags and tags 404s before loading", async () => {
    for (const slug of ["a".repeat(120), "bad,slug", "Uppercase", "a".repeat(121)]) {
      const { load, tags, events } = harness(() => new Response(null, { status: 404 }));
      await assert.rejects(load(route).default({ params: Promise.resolve({ slug, n: "2" }) }), /not found/);
      assert.deepEqual(tags, slug.length === 120 ? [`company-${slug}`] : []);
      assert.deepEqual(events, slug.length === 120 ? ["tag", "fetch"] : ["fetch"]);
    }
  });

  test(route + " propagates runtime API errors", async () => {
    const { load, reads } = harness(() => new Response("unavailable", { status: 503 }));
    const page = load(route);
    const props = { params: Promise.resolve({ slug: "example", n: "2" }) };
    await assert.rejects(page.generateMetadata(props), /503/);
    await assert.rejects(page.default(props), /503/);
    assert.equal(reads.length, 1);
  });
}

test("curated company pages retain metadata and render without API reads", async () => {
  const { load, reads, tags } = harness();
  const page = load(companyRoutes[0]);
  const props = { params: Promise.resolve({ slug: "google" }) };
  await page.default(props);
  assert.equal((await page.generateMetadata(props)).alternates.canonical, "/companies/google");
  assert.deepEqual(reads, []);
  assert.deepEqual(tags, ["company-google"]);
});

test("company pagination retains redirects and out-of-range notFound behaviour", async () => {
  const { load, reads } = harness();
  const page = load(companyRoutes[1]);
  await assert.rejects(page.default({ params: Promise.resolve({ slug: "example", n: "1" }) }), /redirect: \/companies\/example/);
  assert.deepEqual(reads, []);
  const props = { params: Promise.resolve({ slug: "example", n: "4" }) };
  const metadata = await page.generateMetadata(props);
  assert.equal(metadata.robots.index, false);
  await assert.rejects(page.default(props), /not found/);
  assert.equal(reads.length, 1);
});

test("detail API no-store options skip both Next caches and retain company expiry", async () => {
  const { load, reads, cached } = harness(url => Response.json(url.includes("/similar?") ? [] : company));
  const api = load("lib/api.ts");
  await api.getOpportunity("example", 0);
  await api.getSimilarOpportunities("example", 6, 0);
  const snapshot = await api.getCompanyPage("example", 1, 20, 0);
  assert.equal(snapshot.expiresAt - snapshot.loadedAt, week * 1000);
  assert.equal(reads.length, 3);
  assert.ok(reads.every(([, options]) => options.cache === "no-store" && options.next === undefined));
  assert.deepEqual(cached, []);
});

test("existing API callers keep cache windows, including the OG route and client recovery", async () => {
  const { load, reads, cached } = harness(url => Response.json(url.includes("/similar?") ? [] : company));
  const api = load("lib/api.ts");
  await api.getOpportunity("example");
  await api.getOpportunity("example", 86400);
  await api.getSimilarOpportunities("example");
  const snapshot = await api.getCompanyPage("example");
  assert.equal(reads[0][1].next.revalidate, week);
  assert.equal(reads[1][1].next.revalidate, 86400);
  assert.deepEqual(cached.map(options => options.revalidate), [week, week]);
  assert.equal(snapshot.expiresAt - snapshot.loadedAt, week * 1000);

  const client = harness(() => Response.json(company), { window: {} });
  const clientSnapshot = await client.load("lib/api.ts").getCompanyPage("example", 1, 20);
  assert.deepEqual(client.cached, []);
  assert.equal(client.reads[0][1].cache, "no-store");
  assert.equal(clientSnapshot.expiresAt - clientSnapshot.loadedAt, week * 1000);
});

test("only the company directory owns the loading boundary", () => {
  for (const filename of ["app/companies/(directory)/page.tsx", "app/companies/(directory)/loading.tsx", "app/companies/error.tsx"]) {
    assert.ok(fs.existsSync(new URL("../" + filename, import.meta.url)), filename);
  }
  for (const filename of ["app/loading.tsx", "app/companies/loading.tsx", "app/companies/page.tsx", "app/companies/[slug]/loading.tsx", "app/companies/[slug]/page/loading.tsx", "app/companies/[slug]/page/[n]/loading.tsx", "app/opportunity/loading.tsx", "app/opportunity/[slug]/loading.tsx"]) {
    assert.equal(fs.existsSync(new URL("../" + filename, import.meta.url)), false, filename);
  }
});

test("CDN headers target only detail URLs and metadata blocks for every user agent", async () => {
  const config = testModuleLoader({}, { __dirname: "frontend" })("next.config.ts").default;
  const entries = (await config.headers()).filter(entry => entry.headers.some(header => header.key === "Vercel-CDN-Cache-Control"));
  assert.deepEqual(Array.from(entries, entry => entry.source), ["/opportunity/:slug", "/companies/:slug", "/companies/:slug/page/:n"]);
  const { pathToRegexp } = require("next/dist/compiled/path-to-regexp");
  for (const entry of entries) {
    assert.equal(entry.headers[0].key, "Vercel-CDN-Cache-Control");
    assert.equal(entry.headers[0].value, "max-age=604800");
    const matcher = pathToRegexp(entry.source);
    for (const url of ["/opportunity/sitemap/0.xml", "/opportunity/example/opengraph-image", "/companies", "/jobs"]) {
      assert.equal(matcher.test(url), false, url);
    }
  }
  for (const agent of ["", "Mozilla/5.0", "Googlebot", "Twitterbot"]) assert.ok(config.htmlLimitedBots.test(agent));
});

test("the ISR registration guard rejects any detail route registered again", () => {
  const source = fs.readFileSync(new URL("../scripts/check-isr-registration.mjs", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "").replaceAll("import.meta.url", JSON.stringify(import.meta.url));
  const staticRoutes = Object.fromEntries(Object.entries({
    "/": 21600, "/calendar": 21600, "/companies": 86400, "/competitions": 21600,
    "/internships": 21600, "/jobs": 21600, "/remote": 21600, "/scholarships": 21600,
  }).map(([route, seconds]) => [route, { initialRevalidateSeconds: seconds }]));
  const dynamicRoutes = Object.fromEntries([
    "/internships/page/[n]", "/internships/in/[place]", "/internships/role/[role]",
    "/jobs/page/[n]", "/jobs/in/[place]", "/jobs/role/[role]", "/programme/[slug]",
    "/remote/page/[n]", "/scholarships/page/[n]",
  ].map(route => [route, {}]));
  function run(extra) {
    const errors = [];
    let exitCode = 0;
    try {
      vm.runInNewContext(source, {
        fs: { existsSync: () => true, readFileSync: () => JSON.stringify({ routes: staticRoutes, dynamicRoutes: { ...dynamicRoutes, ...extra } }) },
        path: require("node:path"), fileURLToPath: require("node:url").fileURLToPath,
        console: { error: message => errors.push(message), log() {} },
        process: { exit(code) { exitCode = code; throw new Error("exit"); } },
      });
    } catch (error) {
      if (!exitCode) throw error;
    }
    return { errors, exitCode };
  }
  assert.equal(run({}).exitCode, 0);
  for (const route of ["/opportunity/[slug]", "/companies/[slug]", "/companies/[slug]/page/[n]"]) {
    const { errors, exitCode } = run({ [route]: {} });
    assert.equal(exitCode, 1);
    assert.ok(errors.includes(route));
  }
});
