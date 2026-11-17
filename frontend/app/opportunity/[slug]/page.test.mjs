// Offline SSR regression: actual page/card JSX, with API and client widgets stubbed.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const frontend = fileURLToPath(new URL("../../../", import.meta.url));
const anchor = ({ children, href, "aria-label": ariaLabel }) => React.createElement("a", { href, "aria-label": ariaLabel }, children);
const label = ({ children }) => React.createElement("span", {}, children);
let current;

function load(filename) {
  const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const loaded = { exports: {} };
  vm.runInNewContext(source, {
    URL,
    module: loaded,
    exports: loaded.exports,
    require: (name) => {
      if (name === "next/link") return { default: anchor };
      if (name === "next/navigation") return { notFound() { throw Error("not found"); } };
      if (name === "lucide-react") return new Proxy({}, { get: () => () => null });
      if (name === "@/lib/api") return {
        getOpportunity: async () => current,
        getSimilarOpportunities: async () => [],
      };
      if (name === "@/components/ui/badge") return { Badge: label };
      if (name === "@/components/ui/button") return { Button: label };
      if (name === "@/components/ApplyLink") return {
        default: ({ children, href }) => React.createElement("a", { href, "data-apply": true }, children),
      };
      if (name === "@/components/HoverPrefetchLink") return { default: anchor };
      if (name.startsWith("@/components/")) return { default: () => null };
      if (name.startsWith("@/lib/")) return load(path.join(frontend, name.slice(2) + ".ts"));
      if (name.startsWith(".")) return load(path.resolve(path.dirname(filename), name + ".ts"));
      return require(name);
    },
  });
  return loaded.exports;
}

const page = load(fileURLToPath(new URL("./page.tsx", import.meta.url)));
const card = load(path.join(frontend, "components/OpportunityCard.tsx")).default;
const base = {
  slug: "test-intern",
  title: "Software Engineering Intern",
  company: { name: "Example Co", slug: "example", domain: "example.com", logo_url: null },
  category: "internship", status: "active", safety: null,
  source: "greenhouse", location: "Bengaluru", country: "IN", is_remote: false,
  apply_url: "https://example.com/apply", description_raw: "Build APIs and ship software.",
  posted_at: "2026-11-01T09:00:00Z", first_seen_at: "2026-11-01T09:00:00Z",
  last_seen_at: "2026-11-17T09:00:00Z", is_hidden: false, is_stale: false,
  closed_at: null, deadline: null, deadline_confidence: "unknown", meta: {},
  skills: [], summary: null, reopen_estimate: null,
};
const props = { params: Promise.resolve({ slug: base.slug }) };

for (const [kind, heading] of [
  ["scam", "Warning: reported as a scam"],
  ["recalled", "This listing was withdrawn"],
]) {
  test(`${kind}: source-backed warning precedes title, no Apply or indexing`, async () => {
    current = { ...base, status: "withdrawn", safety: {
      kind, note: "Source recalled this listing <please check>.",
      source_url: "https://example.com/source-notice", flagged_at: "2026-11-17T09:00:00Z",
    } };
    const html = renderToStaticMarkup(await page.default(props));
    assert.match(html, /<section aria-labelledby="listing-safety-heading"/);
    assert.ok(html.indexOf(heading) < html.indexOf("<h1"));
    assert.ok(html.includes("Source recalled this listing &lt;please check&gt;."));
    assert.ok(html.includes("Do not pay any fee or share bank or ID documents."));
    assert.match(html, /href="https:\/\/example.com\/source-notice"[^>]*>Read the source of this warning<\/a>/);
    assert.doesNotMatch(html, /role="alert"|data-apply|application\/ld\+json/);
    assert.ok(!html.includes('href="https://example.com/apply"'));
    const meta = await page.generateMetadata(props);
    assert.equal(meta.robots.index, false);
    const saved = renderToStaticMarkup(React.createElement(card, { item: current }));
    assert.ok(saved.includes(kind === "scam" ? "Warning: reported as a scam" : "Warning: listing withdrawn"));
    assert.ok(saved.includes(`/opportunity/${base.slug}`));
    assert.match(saved, /aria-label="Software Engineering Intern. Warning:/);
  });
}

for (const kind of ["scam", "recalled"]) {
  test(kind + ": warning without a founder reference has no external link", async () => {
    current = { ...base, status: "withdrawn", safety: {
      kind, note: "Removed by the source", source_url: null,
    } };
    const html = renderToStaticMarkup(await page.default(props));
    const warning = html.match(/<section aria-labelledby="listing-safety-heading"[^>]*>[\s\S]*?<\/section>/)?.[0];
    assert.ok(warning);
    assert.ok(warning.includes("Removed by the source"));
    assert.ok(!warning.includes(base.apply_url));
    assert.doesNotMatch(warning, /<a\b/);
    assert.ok(!html.includes(base.apply_url));
    assert.doesNotMatch(html, /data-apply|application\/ld\+json/);
  });
}

test("cleared listing offers Apply and eligible JobPosting markup again", async () => {
  current = base;
  const html = renderToStaticMarkup(await page.default(props));
  assert.match(html, /data-apply/);
  assert.match(html, /application\/ld\+json/);
  assert.doesNotMatch(html, /listing-safety-heading/);
  assert.equal((await page.generateMetadata(props)).robots, undefined);
});
