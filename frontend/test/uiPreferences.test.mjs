import test from "node:test";
import assert from "node:assert/strict";
import { applyReduceMotionAttribute, DEFAULT_PREFERENCES, normalizePreferences, readLocalReduceMotionExplicit, resolveReduceMotionPreference, writeLocalPreferences } from "../src/uiPreferences.js";

test("legacy density and sidebar preferences are ignored without affecting current settings", () => {
  assert.deepEqual(normalizePreferences({
    theme: "dark",
    density: "comfortable",
    hideSidebar: true,
    sidebar_collapsed: true,
    reduce_motion: true,
    visible_columns: ["status", "account", "environment", "last_opened"],
  }), {
    theme: "dark",
    reduce_motion: true,
    visible_columns: ["account", "environment", "last_opened"],
  });
});

test("all optional profile columns may be disabled together", () => {
  assert.deepEqual(normalizePreferences({ visible_columns: [] }).visible_columns, []);
});

test("new preferences use compact optional columns with status managed separately", () => {
  assert.deepEqual(DEFAULT_PREFERENCES.visible_columns, ["account", "environment", "last_opened"]);
  assert.equal(Object.hasOwn(DEFAULT_PREFERENCES, "density"), false);
  assert.equal(Object.hasOwn(DEFAULT_PREFERENCES, "sidebar_collapsed"), false);
});

test("light and dark themes are supported with dark as the default", () => {
  assert.equal(DEFAULT_PREFERENCES.theme, "dark");
  assert.equal(normalizePreferences({ theme: "light" }).theme, "light");
  assert.equal(normalizePreferences({ theme: "dark" }).theme, "dark");
  assert.equal(normalizePreferences({ theme: "unknown" }).theme, "dark");
});

test("reduce motion follows the OS preference when the user has not chosen", () => {
  assert.equal(resolveReduceMotionPreference(null, true), true);
  assert.equal(resolveReduceMotionPreference(null, false), false);
});

test("an explicit reduce motion choice overrides the OS preference", () => {
  assert.equal(resolveReduceMotionPreference(true, false), true);
  assert.equal(resolveReduceMotionPreference(false, true), false);
});

test("the active reduce motion choice is written to the root data attributes", () => {
  const root = { dataset: {} };
  applyReduceMotionAttribute(root, true);
  assert.equal(root.dataset.reduceMotion, "true");
  assert.equal(root.dataset.motion, "reduced");
});

test("an explicit off choice is persisted separately from the OS default", () => {
  const previousWindow = globalThis.window;
  let stored = null;
  globalThis.window = { localStorage: {
    getItem: () => stored,
    setItem: (_key, value) => { stored = value; },
  } };
  try {
    writeLocalPreferences({ ...DEFAULT_PREFERENCES, reduce_motion: false }, false);
    assert.equal(readLocalReduceMotionExplicit(), false);
    assert.equal(JSON.parse(stored).reduce_motion_explicit, false);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
