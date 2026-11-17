// node --test lib/digest.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testModuleLoader } from "../scripts/test-module.mjs";

const component = fn => ({ __esModule: true, default: fn });
const container = ({ children }) => React.createElement("div", null, children);
const hidden = component(() => null);
const overrides = {
  "next/link": component(({ children, ...props }) => React.createElement("a", props, children)),
  "@/components/ui/button": { Button: ({ children, ...props }) => {
    delete props.variant; delete props.size;
    return React.createElement("button", props, children);
  } },
  "@/components/ui/dialog": Object.fromEntries(["Dialog", "DialogContent", "DialogHeader", "DialogTitle", "DialogDescription"].map(name => [name, container])),
  "@/components/account/primitives": {
    ...Object.fromEntries(["ConfirmDialog", "Meter", "SectionHeader", "SettingsCard", "StatusPill"].map(name => [name, container])),
    EmptyState: ({ title, description }) => React.createElement("p", null, title, " ", description),
  },
  "@/components/ui/skeleton": { Skeleton: () => null },
  "@/components/ui/switch": { Switch: () => null },
  "@/components/CompanyFavicon": hidden,
  "@/components/CompanyPicker": hidden,
  "@/components/DomainPicker": hidden,
  "@/components/ListingFeedback": { ListingFailure: () => null },
  "@/lib/api": { DigestPreviewRateLimitError: class extends Error {} },
};
const load = testModuleLoader(overrides);
const helpers = load("lib/digest.ts");
const NotificationsSection = load("components/account/NotificationsSection.tsx").default;
const { DigestSampleContent } = load("components/DigestSample.tsx");
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const item = { kind: "opportunity", slug: "real-role", title: "Research Intern", company_name: "Example Co", category: "internship", deadline: "2031-04-11T12:00:00Z", deadline_precision: "day", deadline_confidence: "explicit" };
const status = { last_sent_at: "2031-04-01T12:00:00Z", last_sent_count: 12, last_attempt_failed: false };
const accountProps = (digest_status, enabled = true) => ({
  account: { notification_prefs: { daily_digest: enabled }, plan: { features: {} }, digest_status },
  accessToken: "test-token", onAccountChange() {},
});
function statusLine(digestStatus, enabled = true) {
  const html = render(NotificationsSection, accountProps(digestStatus, enabled));
  return html.match(/<p[^>]*data-testid="digest-status"[^>]*>(.*?)<\/p>/s)[1].replace(/<[^>]+>/g, "");
}

test("original status line remains unchanged without a category breakdown", () => {
  assert.match(statusLine(status), /^Last sent .+ with 12 listings\.$/);
  assert.match(statusLine({ ...status, last_sent_counts_by_category: {} }), /^Last sent .+ with 12 listings\.$/);
  assert.equal(statusLine(null), "No digest has been sent to you yet.");
  assert.equal(statusLine(null, false), "You are not receiving the daily digest.");
});

test("last-send status appends category counts using the listing card labels", () => {
  assert.match(statusLine({ ...status, last_sent_counts_by_category: { job: 8, internship: 4 } }), /with 12 listings \(8 jobs, 4 internships\)\.$/);
  assert.equal(helpers.categoryCounts({ job: 1, hackathon: 2, competition: 1, scholarship: 2, removed: 1, programme_update: 1 }), "1 job, 2 hackathons, 1 competition, 2 scholarships, 1 removed, 1 programme update");
  assert.equal(helpers.categoryCounts({ programme_update: 2 }), "2 programme updates");
});

test("a failed latest attempt preserves the original copy and last successful counts", () => {
  const failed = { ...status, last_attempt_failed: true, last_sent_counts_by_category: { internship: 12 } };
  assert.match(statusLine(failed), /^The latest digest could not be sent\. It will be tried again at the next daily run\. Last sent .+ with 12 listings \(12 internships\)\.$/);
  assert.doesNotMatch(statusLine(failed, false), /It will be tried again/);
});

test("restored preview still shows the real email in an iframe with new-tab links", () => {
  const values = [null, true, { html: "<html><head></head><body>Original email</body></html>" }, "idle"];
  const hooks = { ...React, useState(initial) {
    const state = React.useState(initial);
    return values.length ? [values.shift(), () => {}] : state;
  } };
  const Section = testModuleLoader({ ...overrides, react: hooks })("components/account/NotificationsSection.tsx").default;
  const html = render(Section, accountProps(status));
  assert.match(html, /Preview your next digest/);
  assert.match(html, /<iframe[^>]+srcDoc="[^"]*Original email/);
  assert.match(html, /&lt;base target=&quot;_blank&quot;&gt;/);
  assert.match(html, /sandbox="allow-popups allow-popups-to-escape-sandbox"/);
});

const sample = { date: "2031-04-01", empty: false, counts_by_category: { internship: 1 }, items: [item] };

test("public sample renders a readable date, plain-text picks and a sign-in note", () => {
  const html = render(DigestSampleContent, { sample });
  assert.match(html, /Example from today&#x27;s digest/);
  assert.match(html, /<time dateTime="2031-04-01">1 Apr<\/time>/);
  assert.match(html, /Research Intern/);
  // Inside the sign-in dialog: no links that would leave the listing being applied to.
  assert.doesNotMatch(html, /href=/);
  assert.match(html, /Sign in above to get picks like these by email each day\./);
});

test("public sample renders nothing when absent, empty or when fetch fails", async () => {
  for (const sample of [null, { empty: true, items: [] }, { empty: false, items: [] }]) assert.equal(render(DigestSampleContent, { sample }), "");
  for (const fetch of [async () => new Response(null, { status: 503 }), async () => { throw new Error("offline"); }, async () => new Response("bad json"), async () => Response.json({ ...sample, empty: true, items: [] })]) {
    const service = testModuleLoader({}, { fetch })("lib/digest.ts");
    const result = await service.getDigestSample();
    assert.equal(result, null);
    assert.equal(render(DigestSampleContent, { sample: result }), "");
  }
});

test("public sample fetch includes no authorization or personal request options", async () => {
  const service = testModuleLoader({}, { fetch: async (url, options) => {
    assert.match(url, /\/digest\/sample$/);
    assert.equal(options.headers, undefined);
    assert.equal(options.cache, undefined);
    return Response.json(sample);
  } })("lib/digest.ts");
  assert.deepEqual(await service.getDigestSample(), sample);
  const html = render(DigestSampleContent, { sample: { ...sample, items: Array.from({ length: 8 }, (_, index) => ({ ...item, slug: `role-${index}`, title: `Role ${index}` })) } });
  assert.equal((html.match(/<li>/g) ?? []).length, 6);
});
