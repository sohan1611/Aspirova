// Run with node --test lib/howItWorks.test.mjs (Node 23.6+).
import assert from "node:assert/strict";
import vm from "node:vm";
import { test } from "node:test";
import {
  HOW_IT_WORKS_STORAGE_KEY,
  HOW_IT_WORKS_DISMISSED_SCRIPT,
  isHowItWorksDismissed,
} from "./howItWorks.ts";

test("dismissal respects the exact storage key and value", () => {
  assert.equal(HOW_IT_WORKS_STORAGE_KEY, "aspirova.howItWorks.dismissed");
  for (const value of [null, "", "0", "true", "1", "11"]) {
    const storage = {
      getItem(key) {
        assert.equal(key, HOW_IT_WORKS_STORAGE_KEY);
        return value;
      },
    };
    assert.equal(isHowItWorksDismissed(storage), value === "1");
  }
});

test("throwing storage is treated as not dismissed", () => {
  assert.equal(isHowItWorksDismissed({
    getItem() { throw new Error("Storage blocked"); },
  }), false);
});

test("pre-paint script sets the attribute only for the value 1", () => {
  for (const value of [null, "", "0", "true", "1", "11"]) {
    const attributes = [];
    vm.runInNewContext(HOW_IT_WORKS_DISMISSED_SCRIPT, {
      localStorage: {
        getItem(key) {
          assert.equal(key, HOW_IT_WORKS_STORAGE_KEY);
          return value;
        },
      },
      document: { documentElement: {
        setAttribute(...args) { attributes.push(args); },
      } },
    });
    assert.deepEqual(attributes, value === "1" ? [["data-hiw-dismissed", ""]] : []);
  }
});

test("pre-paint script tolerates blocked storage access and reads", () => {
  const document = { documentElement: {
    setAttribute() { assert.fail("Should remain visible"); },
  } };
  vm.runInNewContext(HOW_IT_WORKS_DISMISSED_SCRIPT, {
    document,
    localStorage: { getItem() { throw new Error("Storage blocked"); } },
  });
  vm.runInNewContext(HOW_IT_WORKS_DISMISSED_SCRIPT, {
    document,
    get localStorage() { throw new Error("Storage blocked"); },
  });
});
