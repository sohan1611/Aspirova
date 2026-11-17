// Run with: node --test lib/actionCenter.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { testModuleLoader } from "../scripts/test-module.mjs";

const component = fn => ({ __esModule: true, default: fn });
const Button = ({ children, ...props }) => {
  delete props.variant;
  return React.createElement("button", props, children);
};
const load = testModuleLoader({
  "next/link": component(({ children, ...props }) => React.createElement("a", props, children)),
  "@/components/ApplyLink": component(({ slug, children, ...props }) => {
    delete props.variant;
    return React.createElement("a", { ...props, "data-apply": slug }, children);
  }),
  "@/components/ui/button": { Button },
}, { URL });
const { BOOKMARK_STAGES, stageLabel, bookmarkCounts, isInProgress, isAppliedStage, relevantDate, nextUpItems, actionDateLabel, actionSource } = load("lib/actionCenter.ts");

function item(stage, slug = stage, extra = {}) {
  return {
    slug, title: `Opportunity ${slug}`, bookmark_status: stage,
    status: "active", safety: null, meta: null,
    status_date: null, status_changed_at: null, note: null,
    deadline: null, closed_at: null, category: "job", deadline_confidence: "explicit",
    company: { name: "Example", slug: "example", domain: "example.com" },
    apply_url: "https://boards.greenhouse.io/example/jobs/123",
    destination: { kind: "ats", host: "boards.greenhouse.io", label: "Greenhouse" },
    ...extra,
  };
}

test("all eight manual stages are in pipeline order, with the Interview label", () => {
  assert.deepEqual(Array.from(BOOKMARK_STAGES, stage => stage.value), ["saved", "planned", "applied", "assessment", "interviewing", "offer", "rejected", "archived"]);
  assert.equal(stageLabel("interviewing"), "Interview");
  assert.deepEqual(Array.from(BOOKMARK_STAGES.filter(stage => isInProgress(stage.value)), stage => stage.value), ["planned", "applied", "assessment", "interviewing"]);
  for (const stage of ["assessment", "interviewing", "offer", "rejected"]) assert.equal(isAppliedStage(stage), true);
  for (const stage of ["saved", "planned", undefined]) assert.equal(isAppliedStage(stage), false);
});

test("tracked counts exclude archived; in progress excludes final decisions", () => {
  const counts = bookmarkCounts(BOOKMARK_STAGES.map(stage => item(stage.value)));
  assert.equal(counts.tracked, 7);
  assert.equal(counts.inProgress, 4);
  for (const stage of BOOKMARK_STAGES) assert.equal(counts.stages[stage.value], 1);
  assert.equal(bookmarkCounts([]).tracked, 0);
});

test("Next up selects unfinished stages and sorts by assessment/interview date, otherwise deadline", () => {
  const items = [
    item("saved"), item("offer"), item("rejected"), item("archived"),
    item("planned", "plan", { status_date: "2099-01-01", deadline: "2099-11-22T12:00:00Z" }),
    item("applied", "applied", { status_date: "2099-01-01", deadline: "2099-11-20T12:00:00Z" }),
    item("assessment", "test", { status_date: "2099-11-19", deadline: "2099-12-30T12:00:00Z" }),
    item("interviewing", "interview", { status_date: "2099-11-21", deadline: "2099-01-01T12:00:00Z" }),
    item("interviewing", "fallback", { deadline: "2099-11-23T12:00:00Z" }),
    item("applied", "undated-b"), item("assessment", "undated-a"),
  ];
  const before = items.map(row => row.slug);
  assert.deepEqual(Array.from(nextUpItems(items), row => row.slug), ["test", "applied", "interview", "plan", "fallback", "undated-a", "undated-b"]);
  assert.deepEqual(items.map(row => row.slug), before);
  assert.equal(relevantDate(items[4]), items[4].deadline);
  assert.equal(nextUpItems([item("saved"), item("offer"), item("archived")]).length, 0);
});

test("status dates use calendar days in UTC and inferred deadlines stay labelled", () => {
  assert.equal(actionDateLabel(item("interviewing", "i", { status_date: "2026-11-21" })), "Interview on 21 Nov");
  assert.equal(actionDateLabel(item("assessment", "a", { status_date: "2028-02-29" })), "Assessment on 29 Feb");
  assert.equal(actionDateLabel(item("applied", "a", { status_date: "2026-11-17" })), "Applied on 17 Nov");
  assert.equal(actionDateLabel(item("planned", "p", { deadline: "2026-11-21T00:00:00Z", deadline_confidence: "inferred" })), "Listing deadline ~21 Nov");
  assert.equal(actionDateLabel(item("planned")), null);
});

function renderSource(row) {
  return renderToStaticMarkup(React.createElement(load("components/ActionSource.tsx").default, { item: row }));
}

test("open source uses describeApply's honest destination caption and existing ApplyLink", () => {
  const html = renderSource(item("planned"));
  assert.match(html, /data-apply="planned"/);
  assert.match(html, /Example&#x27;s careers listing, hosted on Greenhouse \(boards.greenhouse.io\)/);
  assert.match(html, /Aspirova never handles your application/);
  const board = renderSource(item("applied", "board", { destination: { kind: "job_board", host: "remoteok.com", label: "RemoteOK" } }));
  assert.match(board, /RemoteOK is a job board/);
});

test("early closure, explicit past deadline and estimated deadline render warnings and verification links", () => {
  for (const extra of [{ closed_at: "2026-11-16T00:00:00Z" }, { deadline: "2000-01-01T00:00:00Z" }, { status: "closed" }]) {
    const html = renderSource(item("applied", "closed", extra));
    assert.match(html, /Applications closed/);
    assert.match(html, /Verify on Example/);
    assert.match(html, /check whether it is still open/);
    assert.doesNotMatch(html, /data-apply/);
  }
  assert.match(renderSource(item("planned", "estimated", { deadline: "2000-01-01T00:00:00Z", deadline_confidence: "inferred" })), /Applications may have closed/);
});

test("withdrawn and scam listings never render their apply URL or ApplyLink", () => {
  for (const extra of [
    { status: "withdrawn" },
    { safety: { kind: "recalled", note: "Recalled by organiser", source_url: "https://example.com/warning" } },
    { safety: { kind: "scam", note: "Reported as scam", source_url: "https://example.com/warning" } },
    { meta: { safety: { kind: "scam" } } },
  ]) {
    const row = item("interviewing", "unsafe", extra);
    assert.equal(actionSource(row).href, null);
    const html = renderSource(row);
    assert.doesNotMatch(html, /boards.greenhouse.io|data-apply|Apply on/);
    assert.match(html, /Do not pay any fee or share bank or ID documents/);
    if (extra.safety) assert.match(html, /Read the source of this warning/);
    if (extra.safety?.kind === "scam") assert.match(html, /Warning: reported as a scam/);
  }
  assert.equal(actionSource(item("planned", "bad-url", { apply_url: "javascript:alert(1)" })).href, null);
});

test("Next up renders dates, note excerpts, status and a saved-items empty state", () => {
  const NextUp = load("components/NextUp.tsx").default;
  const render = items => renderToStaticMarkup(React.createElement(NextUp, { items, onPlanNext() {} }));
  const html = render([item("interviewing", "next", { status_date: "2026-11-21", note: "Bring portfolio" })]);
  assert.match(html, /Next up/);
  assert.match(html, /Interview on 21 Nov/);
  assert.match(html, /Bring portfolio/);
  assert.match(html, /line-clamp-2/);
  const empty = render([item("saved"), item("offer")]);
  assert.match(empty, /Nothing unfinished/);
  assert.match(empty, /Plan from saved items/);
});

test("tracker controls initially show only the labelled stage and collapsed disclosure", () => {
  const Controls = load("components/BookmarkControls.tsx").default;
  const render = pending => renderToStaticMarkup(React.createElement(Controls, {
    item: item("interviewing"), pending, onChange: async () => true,
  }));
  const html = render(false);
  const labels = [...html.matchAll(/<label for="([^"]+)"/g)];
  assert.equal(labels.length, 1);
  for (const [, id] of labels) assert.ok(html.includes(`id="${id}"`));
  assert.match(html, /<option value="interviewing" selected="">Interview<\/option>/);
  assert.match(html, /Add date or note/);
  assert.match(html, /aria-expanded="false"/);
  const panelId = html.match(/aria-controls="([^"]+)"/)[1];
  assert.ok(html.includes(`id="${panelId}" hidden=""`));
  assert.doesNotMatch(html, /<form|type="date"|<textarea|Ready to save|Save date and note/);
  const pending = render(true);
  assert.match(pending, /aria-busy="true"/);
  assert.match(pending, /Saving changes/);
  assert.match(pending, /<select[^>]*disabled/);
  assert.match(pending, /role="status" aria-live="polite" class="sr-only"/);
});

test("collapsed date and note summaries use the current stage and never substitute the listing deadline", () => {
  const Controls = load("components/BookmarkControls.tsx").default;
  const render = extra => renderToStaticMarkup(React.createElement(Controls, {
    item: item("interviewing", "summary", extra), pending: false, onChange: async () => true,
  }));
  const both = render({ status_date: "2026-11-21", note: "Revise DSA + system design" });
  assert.match(both, /Interview on 21 Nov · Revise DSA \+ system design/);
  assert.match(both, />Edit<\/button>/);
  assert.doesNotMatch(both, /Add date or note|<textarea/);
  assert.match(render({ status_date: "2026-11-21" }), /Interview on 21 Nov/);
  assert.match(render({ note: "Revise DSA", deadline: "2099-12-01T00:00:00Z" }), /Revise DSA/);
  assert.doesNotMatch(render({ note: "Revise DSA", deadline: "2099-12-01T00:00:00Z" }), /Listing deadline/);
  assert.match(render({ deadline: "2099-12-01T00:00:00Z" }), /Add date or note/);
});

function controlsHarness(initial, write = async () => true) {
  const hooks = [];
  const focused = [];
  const requests = [];
  let cursor = 0;
  let effects = [];
  let nodes = [];
  let pending = false;
  let row = initial;
  function useState(initialValue) {
    const slot = cursor++;
    if (!(slot in hooks)) hooks[slot] = initialValue;
    return [hooks[slot], value => { hooks[slot] = typeof value === "function" ? value(hooks[slot]) : value; }];
  }
  const controlLoad = testModuleLoader({
    react: {
      ...React, useState, useId: () => "tracker-controls",
      useRef: initialValue => useState({ current: initialValue })[0],
      useEffect: effect => effects.push(effect),
    },
    "@/components/ui/button": { Button },
  }, { URL });
  const Controls = controlLoad("components/BookmarkControls.tsx").default;
  function visit(node) {
    if (Array.isArray(node)) { node.forEach(visit); return; }
    if (!React.isValidElement(node)) return;
    nodes.push(node);
    if (node.props.ref) node.props.ref.current = { focus: () => focused.push(node.props.id ?? "toggle") };
    visit(node.props.children);
  }
  function find(predicate) {
    const found = nodes.find(predicate);
    assert.ok(found, "Expected control to be rendered");
    return found;
  }
  return {
    focused, requests,
    render() {
      cursor = 0; effects = []; nodes = [];
      const tree = Controls({ item: row, pending, onChange: async update => {
        requests.push(update);
        pending = true;
        try {
          const saved = await write(update);
          if (saved) row = {
            ...row, bookmark_status: update.status ?? row.bookmark_status,
            note: update.note === undefined ? row.note : update.note,
            status_date: update.status_date === undefined ? row.status_date : update.status_date,
          };
          return saved;
        } finally { pending = false; }
      } });
      visit(tree);
      const html = renderToStaticMarkup(tree);
      effects.forEach(effect => effect());
      return html;
    },
    toggle() { find(node => "aria-expanded" in node.props).props.onClick(); },
    field(name, value) { find(node => node.props.id === `tracker-controls-${name}`).props.onChange({ target: { value } }); },
    clear(name) { find(node => node.props["aria-label"] === `Clear ${name} for ${row.title}`).props.onClick(); },
    save() { return find(node => node.type === "form").props.onSubmit({ preventDefault() {} }); },
    stage(value) { return find(node => node.type === "select").props.onChange({ target: { value } }); },
  };
}

test("opening the editor reveals labelled fields and closing it restores focus to the disclosure", () => {
  const controls = controlsHarness(item("planned"));
  controls.render();
  assert.deepEqual(controls.focused, []);
  controls.toggle();
  const html = controls.render();
  assert.match(html, /aria-expanded="true"/);
  assert.doesNotMatch(html, /id="tracker-controls-details" hidden/);
  assert.match(html, /type="date"/);
  assert.match(html, /maxLength="1000"/);
  assert.match(html, /Clear date for/);
  assert.match(html, /Clear note for/);
  assert.match(html, /Save date and note/);
  const labels = [...html.matchAll(/<label for="([^"]+)"/g)];
  assert.equal(labels.length, 3);
  for (const [, id] of labels) assert.ok(html.includes(`id="${id}"`));
  assert.deepEqual(controls.focused, ["tracker-controls-date"]);
  controls.toggle();
  assert.doesNotMatch(controls.render(), /<form|<textarea/);
  assert.deepEqual(controls.focused, ["tracker-controls-date", "toggle"]);
});

test("saving date/note announces pending and success, collapses, updates summary and returns focus", async () => {
  let finishWrite;
  const controls = controlsHarness(item("interviewing"), () => new Promise(resolve => { finishWrite = resolve; }));
  controls.render(); controls.toggle(); controls.render();
  controls.field("date", "2026-11-21");
  controls.field("note", "Revise DSA + system design");
  controls.render();
  const saving = controls.save();
  const pending = controls.render();
  assert.match(pending, /Saving changes…/);
  assert.match(pending, /aria-expanded="true"/);
  assert.match(pending, /<input[^>]*disabled/);
  assert.deepEqual(controls.focused, ["tracker-controls-date"]);
  finishWrite(true);
  await saving;
  const saved = controls.render();
  assert.match(saved, /aria-expanded="false"/);
  assert.match(saved, /Interview on 21 Nov · Revise DSA \+ system design/);
  assert.match(saved, /Date and note saved/);
  assert.doesNotMatch(saved, /<textarea|Ready to save/);
  assert.deepEqual(controls.focused, ["tracker-controls-date", "toggle"]);
  assert.equal(controls.requests[0].status_date, "2026-11-21");
  assert.equal(controls.requests[0].note, "Revise DSA + system design");
});

test("a failed save keeps the editor expanded with restored fields and an error announcement", async () => {
  const controls = controlsHarness(item("interviewing", "failed", { status_date: "2026-11-20", note: "Original note" }), async () => false);
  controls.render(); controls.toggle(); controls.render();
  controls.field("date", "2026-11-21"); controls.field("note", "New note"); controls.render();
  await controls.save();
  const failed = controls.render();
  assert.match(failed, /aria-expanded="true"/);
  assert.match(failed, /value="2026-11-20"/);
  assert.match(failed, /Original note<\/textarea>/);
  assert.match(failed, /Couldn&#x27;t save changes. Previous values restored/);
  assert.doesNotMatch(failed, /New note/);
  assert.deepEqual(controls.focused, ["tracker-controls-date"]);
});

test("clearing both optional fields saves nulls and collapses back to Add date or note", async () => {
  const controls = controlsHarness(item("assessment", "clear", { status_date: "2026-11-20", note: "Prepare" }));
  controls.render(); controls.toggle(); controls.render();
  controls.clear("date"); controls.clear("note"); controls.render();
  await controls.save();
  const cleared = controls.render();
  assert.equal(controls.requests[0].note, null);
  assert.equal(controls.requests[0].status_date, null);
  assert.match(cleared, /Add date or note/);
  assert.match(cleared, /aria-expanded="false"/);
  assert.doesNotMatch(cleared, /Assessment on|Prepare|<textarea/);
});

test("partial bookmark updates preserve explicit nulls and encode the slug", async () => {
  let request;
  const api = testModuleLoader({}, { fetch: async (url, options) => {
    request = { url, options };
    return new Response(null, { status: 204 });
  } })("lib/api.ts");
  await api.updateBookmark("test / slug", { note: null, status_date: null }, "test-session");
  assert.match(request.url, /test%20%2F%20slug$/);
  assert.equal(request.options.headers.Authorization, "Bearer test-session");
  assert.deepEqual(JSON.parse(request.options.body), { note: null, status_date: null });
  await api.updateBookmarkStatus("test", "assessment", "test-session");
  assert.deepEqual(JSON.parse(request.options.body), { status: "assessment" });
});

// Exercise the page's real mutation handler with deterministic hook state and
// an unresolved API write, so both the pending view and rollback are observable.
function trackerHarness(items, write = async () => {}, renderControls = false) {
  const hooks = [];
  const stages = new Map(items.map(row => [row.slug, row.bookmark_status]));
  const controls = new Map();
  const errors = [];
  let cursor = 0;
  function useState(initial) {
    const slot = cursor++;
    if (!(slot in hooks)) {
      hooks[slot] = initial && typeof initial === "object" && "requestKey" in initial
        ? { accessToken: "test-token", userId: "test-user", requestKey: 0, items, data: items, status: "results", loadedAt: 123, error: null }
        : initial;
    }
    return [hooks[slot], next => { hooks[slot] = typeof next === "function" ? next(hooks[slot]) : next; }];
  }
  const pageLoad = testModuleLoader({
    react: { ...React, useState, useRef: initial => useState({ current: initial })[0], useMemo: fn => fn(), useEffect() {} },
    "next/link": component(({ children, ...props }) => React.createElement("a", props, children)),
    sonner: { toast: { error: message => errors.push(message) } },
    "@/lib/useSession": { useSessionState: () => ({ session: { access_token: "test-token", user: { id: "test-user" } }, resolved: true }) },
    "@/components/BookmarksProvider": { useBookmarks: () => ({
      statusesReady: true, isSaved: () => true, status: slug => stages.get(slug), syncStatus: (slug, stage) => stages.set(slug, stage),
    }) },
    "@/lib/api": { getBookmarks: async () => items, updateBookmark: write },
    "@/components/HeaderAuth": component(() => null),
    "@/components/BookmarkControls": component(props => {
      controls.set(props.item.slug, props);
      return renderControls ? React.createElement(load("components/BookmarkControls.tsx").default, props) : null;
    }),
    "@/components/OpportunityCard": component(({ item }) => React.createElement("a", { "data-listing": item.slug }, item.title)),
    "@/components/NextUp": component(({ items: next }) => React.createElement("aside", null, next.filter(row => isInProgress(row.bookmark_status)).map(row => React.createElement("p", { key: row.slug }, row.note)))),
  }, { URL });
  const Page = pageLoad("app/saved/page.tsx").default;
  return {
    controls, errors, stages,
    render() { cursor = 0; controls.clear(); return renderToStaticMarkup(Page()); },
  };
}

test("tracker hides archived items by default and renders all active stage filters", () => {
  const tracker = trackerHarness(BOOKMARK_STAGES.map(stage => item(stage.value)));
  const html = tracker.render();
  assert.doesNotMatch(html, /data-listing="archived"/);
  assert.match(html, /All: 7 opportunities \(excluding archived\)/);
  for (const stage of BOOKMARK_STAGES) assert.match(html, new RegExp(`aria-label="${stage.label}: 1 opportunities"`));
  assert.equal(tracker.controls.size, 7);
});

test("each listing precedes its own compact tracking footer inside the same item", () => {
  const tracker = trackerHarness([item("planned", "first"), item("interviewing", "second", { status_date: "2026-11-21", note: "Revise DSA" })], undefined, true);
  const html = tracker.render();
  const units = [...html.matchAll(/<article aria-label="Application tracking for ([^"]+)"[^>]*>([\s\S]*?)<\/article>/g)];
  assert.equal(units.length, 2);
  for (const [, title, content] of units) {
    assert.match(content, new RegExp(`aria-label="Tracking for ${title}"`));
    assert.ok(content.indexOf("data-listing=") < content.indexOf(`aria-label="Tracking for ${title}"`));
    assert.match(content, /aria-expanded="false"/);
    assert.doesNotMatch(content, /<form|<textarea|type="date"|Ready to save/);
  }
  assert.match(units[0][2], /Add date or note/);
  assert.match(units[1][2], /Interview on 21 Nov · Revise DSA/);
  assert.match(units[1][2], />Edit<\/button>/);
});

test("tracker optimistically edits stage, date and note, then restores all values on failure", async () => {
  let failWrite;
  const tracker = trackerHarness([item("planned", "edit", { note: "Before", status_date: "2026-11-20" })],
    () => new Promise((resolve, reject) => { failWrite = reject; }));
  tracker.render();
  const saving = tracker.controls.get("edit").onChange({ status: "assessment", note: "Preparing", status_date: "2026-11-21" });
  tracker.render();
  const pending = tracker.controls.get("edit");
  assert.equal(pending.pending, true);
  assert.equal(pending.item.bookmark_status, "assessment");
  assert.equal(pending.item.status, "active");
  assert.equal(pending.item.note, "Preparing");
  assert.equal(pending.item.status_date, "2026-11-21");
  failWrite(new Error("offline"));
  assert.equal(await saving, false);
  tracker.render();
  const restored = tracker.controls.get("edit");
  assert.equal(restored.pending, false);
  assert.equal(restored.item.bookmark_status, "planned");
  assert.equal(restored.item.note, "Before");
  assert.equal(restored.item.status_date, "2026-11-20");
  assert.equal(tracker.errors.length, 1);
});

test("successful date/note clearing preserves listing and application status", async () => {
  const tracker = trackerHarness([item("assessment", "clear", { note: "Before", status_date: "2026-11-20" })]);
  tracker.render();
  assert.equal(await tracker.controls.get("clear").onChange({ note: null, status_date: null }), true);
  tracker.render();
  const cleared = tracker.controls.get("clear").item;
  assert.equal(cleared.note, null);
  assert.equal(cleared.status_date, null);
  assert.equal(cleared.status, "active");
  assert.equal(cleared.bookmark_status, "assessment");
});
