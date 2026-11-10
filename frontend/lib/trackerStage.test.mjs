// Run with: node --test lib/trackerStage.test.mjs (Node 23.6+ strips the TS types).
import assert from "node:assert/strict";
import { test } from "node:test";
import { trackerStageMessage } from "./trackerStage.ts";

test("describes an applied role", () => {
  assert.equal(trackerStageMessage("applied"), "You marked this as applied.");
});

test("describes an interviewing role", () => {
  assert.equal(trackerStageMessage("interviewing"), "You're interviewing for this role.");
});

test("describes an offer", () => {
  assert.equal(trackerStageMessage("offer"), "You have an offer for this role.");
});

test("omits saved, missing, and unknown stages", () => {
  for (const stage of ["saved", undefined, "unknown", "", "toString", "constructor"]) {
    assert.equal(trackerStageMessage(stage), null, String(stage));
  }
});
