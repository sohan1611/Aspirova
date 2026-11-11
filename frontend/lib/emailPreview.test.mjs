import assert from "node:assert/strict";
import { test } from "node:test";
import { withNewTabLinks } from "./emailPreview.ts";

test("adds a new-tab default inside the email head without changing links or body", () => {
  const body = '<body><a href="https://example.com/apply">View &amp; Apply</a></body>';
  const html = `<!doctype html><html><head><title>Email</title></head>${body}</html>`;
  assert.equal(
    withNewTabLinks(html),
    `<!doctype html><html><head><base target="_blank"><title>Email</title></head>${body}</html>`,
  );
});

test("preserves attributes and case on an existing head", () => {
  assert.equal(
    withNewTabLinks('<HTML><HEAD lang="en"><meta charset="utf-8"></HEAD></HTML>'),
    '<HTML><HEAD lang="en"><base target="_blank"><meta charset="utf-8"></HEAD></HTML>',
  );
});

test("prefixes a base for fragments and empty previews, matching digest behavior", () => {
  for (const html of ["", '<a href="https://example.com">Example</a>', "<header>Sample</header>"]) {
    assert.equal(withNewTabLinks(html), `<base target="_blank">${html}`);
  }
});
