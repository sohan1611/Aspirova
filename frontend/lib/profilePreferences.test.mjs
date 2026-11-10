// Run with node --test lib/profilePreferences.test.mjs (Node 23.6+).
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import ts from "typescript";
import { countrySyncDecision, mergeProfile, normalizeProfile } from "./profilePreferences.ts";

const interests = { stream: "engineering", divisions: ["computing"], interests: ["web"] };

test("normalization keeps uppercase countries and rejects lowercase, junk and missing values", () => {
  assert.equal(normalizeProfile({ country: "US" }).country, "US");
  for (const country of ["us", "in", "USA", "U1", " US ", "", 42, {}, null, undefined]) {
    assert.equal(normalizeProfile({ country }).country, null);
  }
  assert.equal(normalizeProfile({}).country, null);
  assert.equal(normalizeProfile(null).country, null);
  assert.deepEqual(normalizeProfile(interests), { ...interests, country: null });
});

test("saving interests preserves country and saving country preserves interests", () => {
  const profile = { ...interests, country: "IN" };
  assert.deepEqual(mergeProfile(profile, { interests: ["data"] }), {
    ...profile, interests: ["data"],
  });
  assert.deepEqual(mergeProfile(profile, { country: "US" }), { ...profile, country: "US" });
  assert.deepEqual(mergeProfile(profile, { country: null }), { ...profile, country: null });
});

for (const [account, browser, action, country] of [
  ["IN", null, "adopt", "IN"],
  [null, "US", "upload", "US"],
  ["IN", "US", "adopt", "IN"],
  [null, null, "none", null],
  ["in", "US", "upload", "US"],
]) {
  test(`country sync ${account}/${browser} chooses ${action}`, () => {
    assert.deepEqual(countrySyncDecision(account, browser), { action, country });
  });
}

function createCountryStore(accountProfile, browserCountry = null) {
  let profile = normalizeProfile(null);
  let serverProfile = accountProfile;
  const patches = [];
  let reads = 0;
  let beforeRead = async () => {};
  const storage = new Map(browserCountry ? [["aspirova.country", browserCountry]] : []);
  const source = ts.transpileModule(fs.readFileSync(new URL("./country.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  const loaded = { exports: {} };
  const overrides = {
    react: { useSyncExternalStore: () => {} },
    "@/lib/useHydrated": { useHydrated: () => true },
    "@/lib/api": {
      getAccount: async () => {
        reads++;
        await beforeRead();
        return { field_profile: serverProfile };
      },
      updateAccount: async (_token, patch) => {
        patches.push(patch);
        serverProfile = patch.field_profile;
        return { field_profile: serverProfile };
      },
    },
    "@/lib/fieldProfile": {
      readStoredFieldProfile: () => profile,
      storeFieldProfile: (next) => { profile = normalizeProfile(next); },
      hasFieldProfileSelections: (next) => Boolean(next.stream || next.divisions.length || next.interests.length),
    },
    "@/lib/profilePreferences": { normalizeProfile, mergeProfile, countrySyncDecision,
      normalizeCountry: (value) => normalizeProfile({ country: value }).country },
  };
  vm.runInNewContext(source, {
    module: loaded, exports: loaded.exports,
    require: (name) => {
      assert.ok(name in overrides, `Unexpected import ${name}`);
      return overrides[name];
    },
    Event: class {},
    window: {
      localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
      dispatchEvent: () => {},
    },
  });
  return {
    ...loaded.exports, patches, get reads() { return reads; },
    get profile() { return profile; },
    setBeforeRead: (callback) => { beforeRead = callback; },
  };
}

test("signed-out changes stay local and make no account requests", async () => {
  const store = createCountryStore(null);
  await store.storeCountryCode("US");
  await store.saveProfilePreferences(undefined, { ...interests, country: "US" });
  assert.equal(store.readStoredCountryCode(), "US");
  assert.equal(store.reads, 0);
  assert.equal(store.patches.length, 0);
});

test("sign-in adopts account country without PATCH and uploads browser country once", async () => {
  const adopt = createCountryStore({ ...interests, country: "IN" }, "US");
  await adopt.syncAccountPreferences("token", () => true);
  assert.equal(adopt.readStoredCountryCode(), "IN");
  assert.deepEqual(adopt.profile, { ...interests, country: "IN" });
  assert.equal(adopt.patches.length, 0);
  const upload = createCountryStore(interests, "US");
  await upload.syncAccountPreferences("token", () => true);
  await upload.syncAccountPreferences("token", () => true);
  assert.equal(upload.patches.length, 1);
  assert.deepEqual(upload.patches[0].field_profile, { ...interests, country: "US" });
});

test("country and interest saves serialize and each PATCH a merged profile once", async () => {
  const store = createCountryStore({ ...interests, country: "IN" });
  await Promise.all([
    store.storeCountryCode("US", "token"),
    store.saveProfilePreferences("token", { interests: ["data"] }),
  ]);
  assert.equal(store.patches.length, 2);
  assert.deepEqual(store.patches[0].field_profile, { ...interests, country: "US" });
  assert.deepEqual(store.patches[1].field_profile, { ...interests, interests: ["data"], country: "US" });
  assert.equal(store.readStoredCountryCode(), "US");
});

test("late sign-in adoption cannot overwrite a selection made while loading", async () => {
  const store = createCountryStore({ ...interests, country: "IN" }, "GB");
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  store.setBeforeRead(() => pending);
  const sync = store.syncAccountPreferences("token", () => true);
  await Promise.resolve();
  const save = store.storeCountryCode("US", "token");
  release();
  await Promise.all([sync, save]);
  assert.equal(store.readStoredCountryCode(), "US");
  assert.equal(store.patches.length, 1);
  assert.deepEqual(store.patches[0].field_profile, { ...interests, country: "US" });
});

test("onboarding saves country and interests together with one PATCH", async () => {
  const store = createCountryStore({ ...interests, country: "IN" });
  await store.storeCountryCode("US");
  await store.saveProfilePreferences("token", { ...interests, interests: ["data"], country: "US" });
  assert.equal(store.patches.length, 1);
  assert.deepEqual(store.patches[0].field_profile, { ...interests, interests: ["data"], country: "US" });
});

test("a country save retains browser interests when the account has no profile", async () => {
  const store = createCountryStore(null);
  await store.saveProfilePreferences(undefined, interests);
  await store.storeCountryCode("US", "token");
  assert.deepEqual(store.patches[0].field_profile, { ...interests, country: "US" });
});

test("cancelled sign-in work makes no requests and neither country needs no PATCH", async () => {
  const store = createCountryStore(null);
  await store.syncAccountPreferences("token", () => false);
  assert.equal(store.reads, 0);
  await store.syncAccountPreferences("token", () => true);
  assert.equal(store.readStoredCountryCode(), null);
  assert.equal(store.patches.length, 0);
});

test("a failed request keeps the local choice and does not block a later save", async () => {
  const store = createCountryStore({ ...interests, country: "IN" });
  store.setBeforeRead(async () => { throw new Error("offline"); });
  await assert.rejects(store.storeCountryCode("US", "token"), /offline/);
  assert.equal(store.readStoredCountryCode(), "US");
  store.setBeforeRead(async () => {});
  await store.storeCountryCode("GB", "token");
  assert.equal(store.patches.length, 1);
  assert.equal(store.patches[0].field_profile.country, "GB");
});
