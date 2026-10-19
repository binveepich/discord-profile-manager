import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import postcss from "postcss";

const cssText = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const stylesheet = postcss.parse(cssText);

function findRule(selector) {
  return stylesheet.nodes.find((node) => node.type === "rule" && node.selector === selector);
}

function declarations(rule) {
  return Object.fromEntries(rule.nodes.filter((node) => node.type === "decl").map(({ prop, value }) => [prop, value]));
}

test("About and Settings sizing overrides follow the generic modal rule", () => {
  const modalIndex = stylesheet.nodes.indexOf(findRule(".modal-card"));
  const settingsIndex = stylesheet.nodes.indexOf(findRule(".settings-modal"));
  const aboutIndex = stylesheet.nodes.indexOf(findRule(".about-modal"));

  assert.ok(modalIndex >= 0 && modalIndex < settingsIndex);
  assert.ok(modalIndex < aboutIndex);

  const settings = declarations(findRule(".settings-modal"));
  assert.equal(settings.width, "min(1180px, calc(100vw - 48px))");
  assert.equal(settings["max-width"], "1180px");
  assert.equal(settings.height, "auto");
  assert.equal(settings["min-height"], "0");
  assert.equal(settings["max-height"], "min(680px, calc(100vh - 40px))");
  assert.equal(settings.overflow, "hidden");

  const about = declarations(findRule(".about-modal"));
  assert.equal(about.width, "min(560px, calc(100vw - 48px))");
  assert.equal(about["max-width"], "600px");
  assert.equal(about.height, "auto");
  assert.equal(about["min-height"], "0");
  assert.equal(about["max-height"], "min(440px, calc(100vh - 48px))");
  assert.equal(Object.hasOwn(about, "aspect-ratio"), false);
});

test("Settings cards keep natural height and align to the top of grid tracks", () => {
  const grid = declarations(findRule(".settings-modal-body"));
  assert.equal(grid["grid-auto-rows"], "max-content");
  assert.equal(grid["align-items"], "start");
  assert.equal(grid["overflow-y"], "auto");

  const cards = declarations(findRule(".settings-modal .settings-card"));
  assert.equal(cards.height, "auto");
  assert.equal(cards["min-height"], "0");
});

test("requested desktop viewports retain clear dialog margins", () => {
  const viewports = [[1312, 738], [1366, 768], [1600, 900], [1920, 1080]];
  const results = viewports.map(([width, height]) => ({
    width,
    infoWidth: Math.min(560, width - 48),
    infoMaxHeight: Math.min(440, height - 48),
    settingsWidth: Math.min(1180, width - 48),
    settingsMaxHeight: Math.min(680, height - 40),
  }));

  assert.deepEqual(results.map(({ infoWidth }) => infoWidth), [560, 560, 560, 560]);
  assert.deepEqual(results.map(({ infoMaxHeight }) => infoMaxHeight), [440, 440, 440, 440]);
  assert.deepEqual(results.map(({ settingsWidth }) => settingsWidth), [1180, 1180, 1180, 1180]);
  assert.deepEqual(results.map(({ settingsMaxHeight }) => settingsMaxHeight), [680, 680, 680, 680]);
  assert.deepEqual(results.map(({ width, settingsWidth }) => (width - settingsWidth) / 2), [66, 93, 210, 370]);
});
