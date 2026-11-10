// Run with: node --test lib/safeUrl.test.mjs (Node 23.6+ strips the TS types).
import assert from "node:assert/strict";
import { test } from "node:test";
import { safeExternalUrl } from "./safeUrl.ts";

test("keeps absolute web links exactly as given", () => {
  for (const url of [
    "https://jobs.example.com/apply/1",
    "http://example.com/a?utm_source=aspirova&x=%20y",
    "HTTPS://EXAMPLE.COM/Path",
  ]) {
    assert.equal(safeExternalUrl(url), url);
  }
  assert.equal(safeExternalUrl("  https://example.com/padded  "), "https://example.com/padded");
});

test("rejects script, data, file and relative or malformed links", () => {
  for (const url of [
    "javascript:alert(document.cookie)",
    "JaVaScRiPt:alert(1)",
    "\tjavascript:alert(1)",
    "java\nscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "mailto:jobs@example.com",
    "/jobs/123",
    "//evil.example.com/x",
    "jobs.example.com/apply",
    "https://",
    "https://[broken",
    "",
    "   ",
    null,
    undefined,
  ]) {
    assert.equal(safeExternalUrl(url), null, String(url));
  }
});
